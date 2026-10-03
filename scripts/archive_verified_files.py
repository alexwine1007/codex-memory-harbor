#!/usr/bin/env python3
"""Explicitly authorized file archiving; not a Runtime/backup-content adapter.

Copy bytes, verify SHA-256, retain a rollback file until independent validation,
then leave an absolute link at the original path. Never extracts archive contents.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def signature(path):
    info = Path(path).stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def no_open_handles(path):
    result = subprocess.run(["lsof", "-nP", "-Fp", str(path)], capture_output=True)
    if result.returncode not in (0, 1) or result.stdout or result.stderr:
        raise RuntimeError("文件句柄检查不通过，停止迁移")


def append_receipt(path, record):
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


def archive_file(source, target, receipt, check_volume, check_handles=no_open_handles):
    source, target, receipt = Path(source), Path(target), Path(receipt)
    if not source.is_absolute() or not target.is_absolute():
        raise ValueError("必须使用绝对路径")
    rollback = source.with_name(source.name + ".harbor-archive-rollback")
    check_volume()
    if source.is_symlink():
        record = previous_record(receipt, source, target)
        if (not record or os.readlink(source) != str(target)
                or target.stat().st_size != record["bytes"]
                or digest(source) != record["sha256"]):
            raise RuntimeError("已有链接缺少匹配的校验记录")
        if rollback.exists():
            check_handles(rollback)
            if rollback.stat().st_size != record["bytes"] or digest(rollback) != record["sha256"]:
                raise RuntimeError("回滚副本校验不通过，保留本地文件")
            check_volume()
            rollback.unlink()
        return dict(record, status="already_verified")
    if not source.is_file() or target.exists() or target.is_symlink() or rollback.exists():
        raise RuntimeError("来源或目标状态不符合安全条件")
    check_handles(source)
    before = signature(source)
    hasher = hashlib.sha256()
    with source.open("rb") as original, target.open("xb") as copied:
        for chunk in iter(lambda: original.read(8 * 1024 * 1024), b""):
            copied.write(chunk)
            hasher.update(chunk)
        copied.flush()
        os.fsync(copied.fileno())
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
        check_volume()
        if (os.readlink(source) != str(target) or source.stat().st_size != before[2]
                or digest(source) != expected or digest(rollback) != expected):
            raise RuntimeError("独立复核失败")
        record = {"source": str(source), "target": str(target), "bytes": before[2],
                  "sha256": expected, "status": "verified_before_release"}
        append_receipt(receipt, record)
        check_handles(rollback)
        check_volume()
    except BaseException:
        if source.is_symlink() and os.readlink(source) == str(target):
            source.unlink()
        if not source.exists() and not source.is_symlink():
            os.rename(rollback, source)
        raise
    rollback.unlink()
    append_receipt(receipt, dict(record, status="local_entity_released"))
    return dict(record, status="local_entity_released")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--volume", required=True)
    parser.add_argument("--volume-uuid", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    volume = Path(args.volume)
    destination = Path(args.destination)
    if volume.parent != Path("/Volumes") or not destination.is_relative_to(volume):
        parser.error("目标必须位于指定的 /Volumes 外置卷中")
    sources = [Path(item) for item in args.source]
    if len({item.name for item in sources}) != len(sources):
        parser.error("本批次文件名重复")

    def check_volume():
        info = plistlib.loads(subprocess.check_output(["diskutil", "info", "-plist", str(volume)]))
        if info.get("VolumeUUID") != args.volume_uuid or info.get("MountPoint") != str(volume):
            raise RuntimeError("外置卷身份不匹配，停止操作")

    check_volume()
    if not args.execute:
        print(json.dumps({"sources": [str(item) for item in sources],
                          "destination": str(destination)}, ensure_ascii=False))
        return
    destination.mkdir(parents=True, exist_ok=True)
    receipt = destination / "archive-receipt.jsonl"
    for number, source in enumerate(sources, 1):
        print(f"[{number}/{len(sources)}] 开始复制与校验：{source.name}", flush=True)
        record = archive_file(source, destination / source.name, receipt, check_volume)
        print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
