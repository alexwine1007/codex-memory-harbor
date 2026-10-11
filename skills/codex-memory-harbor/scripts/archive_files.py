#!/usr/bin/env python3
"""Explicitly authorized file archiving; not a Runtime/backup-content adapter.

Copy bytes, verify SHA-256, retain a rollback file until independent validation,
then leave an absolute link at the original path. Never extracts archive contents.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import time


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def signature(path):
    info = Path(path).stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def durable_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def safe_directory(path):
    for ancestor in [path, *path.parents]:
        if ancestor.is_symlink():
            raise RuntimeError("目标父目录包含链接，停止操作")
    path.mkdir(parents=True, exist_ok=True)


@contextmanager
def source_lock(source):
    # Lock identity is the original absolute path, independent of the chosen drive.
    directory = Path(os.environ.get("CODEX_HARBOR_FILE_LOCK_DIR", str(Path.home() / ".codex/memory-harbor/file-locks")))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (hashlib.sha256(str(source).encode()).hexdigest() + ".lock")
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("同一文件已有停泊操作，停止重复执行") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def no_open_handles(path):
    result = subprocess.run(["lsof", "-nP", "-Fp", str(path)], capture_output=True, timeout=10)
    if result.returncode not in (0, 1) or result.stdout or result.stderr:
        raise RuntimeError("文件句柄检查不通过，停止迁移")


def append_receipt(path, record):
    if Path(path).is_symlink() or Path(path).parent.resolve() != Path(path).parent:
        raise RuntimeError("校验记录路径包含链接，停止写入")
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def previous_record(receipt, source, target):
    if not Path(receipt).exists():
        return None
    found = None
    with Path(receipt).open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if record["source"] == str(source) and record["target"] == str(target):
                found = record
    return found


def read_source_plan(path):
    """Read a frozen explicit list; never expand a glob during execution."""
    with Path(path).open(encoding="utf-8") as stream:
        plan = json.load(stream)
    rows = plan["files"]
    if not rows or plan["count"] != len(rows):
        raise ValueError("清单数量不匹配")
    if plan["total_bytes"] != sum(row["bytes"] for row in rows):
        raise ValueError("清单字节数不匹配")
    if len({row["source"] for row in rows}) != len(rows):
        raise ValueError("清单来源重复")
    for row in rows:
        if not Path(row["source"]).is_absolute():
            raise ValueError("清单来源必须使用绝对路径")
        for key in ("bytes", "mtime_ns", "inode"):
            if not isinstance(row[key], int) or row[key] < 0:
                raise ValueError("清单文件元数据无效")
        if plan.get("schema") == "memory-harbor-project-files-v1":
            root = Path(plan["project_root"])
            relative = Path(row["relative"])
            if (not root.is_absolute() or relative.is_absolute() or ".." in relative.parts
                    or relative == Path(".") or root / relative != Path(row["source"])):
                raise ValueError("项目清单路径越界或不匹配")
            if root.resolve() != root or Path(row["source"]).parent.resolve() != Path(row["source"]).parent:
                raise ValueError("项目目录或父目录已经改为链接")
            if root.is_relative_to(Path("/Volumes")):
                raise ValueError("项目来源不能位于外置卷")
    return rows


def verify_planned_source(row):
    source = Path(row["source"])
    if source.is_symlink():
        # archive_file separately verifies the exact target and prior receipt.
        return
    info = source.stat()
    if (not source.is_file() or info.st_size != row["bytes"]
            or info.st_mtime_ns != row["mtime_ns"] or info.st_ino != row["inode"]):
        raise RuntimeError("文件与已确认清单不一致，停止操作")
    if any(info_value != row[key] for key, info_value in (("device", info.st_dev), ("ctime_ns", info.st_ctime_ns)) if key in row):
        raise RuntimeError("文件与已确认清单不一致，停止操作")


def archive_file(source, target, receipt, check_volume, check_handles=no_open_handles, keep_local=False):
    with source_lock(Path(source)):
        return _archive_file(source, target, receipt, check_volume, check_handles, keep_local)


def _archive_file(source, target, receipt, check_volume, check_handles, keep_local):
    source, target, receipt = Path(source), Path(target), Path(receipt)
    if not source.is_absolute() or not target.is_absolute():
        raise ValueError("必须使用绝对路径")
    rollback = source.with_name(source.name + ".harbor-archive-rollback")
    identity = check_volume() or {}
    if receipt.is_symlink() or receipt.parent.resolve() != receipt.parent:
        raise RuntimeError("校验记录路径不安全，停止操作")
    if source.is_symlink():
        record = previous_record(receipt, source, target)
        if (not record or os.readlink(source) != str(target)
                or target.stat().st_size != record["bytes"]
                or digest(source) != record["sha256"]
                or identity.get("volume_uuid") and record.get("volume_uuid") != identity["volume_uuid"]):
            raise RuntimeError("已有链接缺少匹配的校验记录")
        if rollback.exists() and not keep_local:
            if rollback.is_symlink():
                raise RuntimeError("回滚副本不是本机普通文件，停止释放")
            check_handles(rollback)
            if rollback.stat().st_size != record["bytes"] or digest(rollback) != record["sha256"]:
                raise RuntimeError("回滚副本校验不通过，保留本地文件")
            check_volume()
            if digest(target) != record["sha256"]:
                raise RuntimeError("外部实体发生变化，保留本地副本")
            rollback.unlink()
            durable_directory(source.parent)
        return dict(record, status="already_verified")
    if (not source.is_file() or source.stat().st_nlink != 1 or source.parent.resolve() != source.parent
            or target.exists() or target.is_symlink() or rollback.exists() or rollback.is_symlink()):
        raise RuntimeError("来源或目标状态不符合安全条件")
    check_handles(source)
    before = signature(source)
    safe_directory(target.parent)
    if target.parent.resolve() != target.parent:
        raise RuntimeError("目标父目录包含链接，停止操作")
    hasher = hashlib.sha256()
    with source.open("rb") as original, target.open("xb") as copied:
        for chunk in iter(lambda: original.read(8 * 1024 * 1024), b""):
            copied.write(chunk)
            hasher.update(chunk)
        copied.flush()
        os.fsync(copied.fileno())
    durable_directory(target.parent)
    expected = hasher.hexdigest()
    check_volume()
    if signature(source) != before or target.stat().st_size != before[2] or digest(target) != expected:
        raise RuntimeError("复制校验不通过，原文件未变更")
    check_handles(source)
    if signature(source) != before:
        raise RuntimeError("来源发生变化，原文件未变更")
    os.rename(source, rollback)
    try:
        source.symlink_to(target)
        durable_directory(source.parent)
        check_volume()
        if (os.readlink(source) != str(target) or source.stat().st_size != before[2]
                or digest(source) != expected or digest(rollback) != expected):
            raise RuntimeError("独立复核失败")
        record = {"source": str(source), "target": str(target), "bytes": before[2],
                  "sha256": expected, "status": "verified_before_release", "recorded_at": int(time.time()), **identity}
        append_receipt(receipt, record)
        check_handles(rollback)
        check_volume()
        if digest(target) != expected or digest(rollback) != expected:
            raise RuntimeError("释放前内容发生变化，保留本地文件")
    except BaseException:
        if source.is_symlink() and os.readlink(source) == str(target):
            source.unlink()
        if not source.exists() and not source.is_symlink():
            os.rename(rollback, source)
        raise
    if keep_local:
        return dict(record, status="verified_with_local_backup")
    rollback.unlink()
    durable_directory(source.parent)
    append_receipt(receipt, dict(record, status="local_entity_released"))
    return dict(record, status="local_entity_released")


def restore_file(source, target, receipt, check_volume, check_handles=no_open_handles):
    """Restore verified bytes at the original path; keep the external copy intact."""
    source, target, receipt = Path(source), Path(target), Path(receipt)
    with source_lock(source):
        identity = check_volume() or {}
        record = previous_record(receipt, source, target)
        if (not source.is_symlink() or os.readlink(source) != str(target) or not record
                or source.parent.resolve() != source.parent
                or target.stat().st_size != record["bytes"] or digest(target) != record["sha256"]
                or identity.get("volume_uuid") and record.get("volume_uuid") != identity["volume_uuid"]):
            raise RuntimeError("原路径、外部实体或校验记录不一致，停止恢复")
        check_handles(target)
        rollback = source.with_name(source.name + ".harbor-archive-rollback")
        temporary = source.with_name(source.name + ".harbor-restore-temp")
        if rollback.is_symlink():
            raise RuntimeError("本地回滚副本是链接，停止恢复")
        if rollback.exists():
            check_handles(rollback)
            if rollback.stat().st_size != record["bytes"] or digest(rollback) != record["sha256"]:
                raise RuntimeError("本地回滚副本已变化，停止恢复")
            replacement = rollback
        else:
            with target.open("rb") as original, temporary.open("xb") as copied:
                for chunk in iter(lambda: original.read(8 * 1024 * 1024), b""):
                    copied.write(chunk)
                copied.flush(); os.fsync(copied.fileno())
            if temporary.stat().st_size != record["bytes"] or digest(temporary) != record["sha256"]:
                raise RuntimeError("恢复副本校验失败，保留外部原件")
            replacement = temporary
        check_volume()
        if digest(target) != record["sha256"] or os.readlink(source) != str(target):
            raise RuntimeError("恢复期间来源发生变化，停止替换")
        os.replace(replacement, source)
        durable_directory(source.parent)
        result = dict(record, status="restored_local_regular_file")
        append_receipt(receipt, result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--source", action="append")
    inputs.add_argument("--source-plan", help="含 files/count/total_bytes 的冻结 JSON 清单")
    parser.add_argument("--destination", required=True)
    parser.add_argument("--volume", required=True)
    parser.add_argument("--volume-uuid", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--release-local", action="store_true", help="项目文件独立复核通过后释放本地实体；默认保留副本")
    parser.add_argument("--restore", action="store_true", help="按原确认清单恢复本机普通文件，外部实体保留")
    args = parser.parse_args()
    volume = Path(args.volume)
    destination = Path(args.destination)
    if volume.parent != Path("/Volumes") or not destination.is_relative_to(volume):
        parser.error("目标必须位于指定的 /Volumes 外置卷中")
    rows = read_source_plan(args.source_plan) if args.source_plan else None
    project_plan = bool(rows and "relative" in rows[0])
    sources = [Path(row["source"]) for row in rows] if rows else [Path(item) for item in args.source]
    if not project_plan and len({item.name for item in sources}) != len(sources):
        parser.error("本批次文件名重复")

    def check_volume():
        info = plistlib.loads(subprocess.check_output(["diskutil", "info", "-plist", str(volume)]))
        if info.get("VolumeUUID") != args.volume_uuid or info.get("MountPoint") != str(volume):
            raise RuntimeError("外置卷身份不匹配，停止操作")
        return {"volume_uuid": args.volume_uuid, "volume_path": str(volume)}

    check_volume()
    if rows:
        for row in rows:
            verify_planned_source(row)
    if not args.execute:
        print(json.dumps({"sources": [str(item) for item in sources],
                          "destination": str(destination)}, ensure_ascii=False))
        return
    safe_directory(destination)
    receipt = destination / "archive-receipt.jsonl"
    for number, source in enumerate(sources, 1):
        if rows and not args.restore:
            verify_planned_source(rows[number - 1])
        print(f"[{number}/{len(sources)}] 开始复制与校验：{source.name}", flush=True)
        relative = rows[number - 1]["relative"] if project_plan else source.name
        if args.restore:
            record = restore_file(source, destination / relative, receipt, check_volume)
        else:
            record = archive_file(source, destination / relative, receipt, check_volume,
                                  keep_local=project_plan and not args.release_local)
        print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
