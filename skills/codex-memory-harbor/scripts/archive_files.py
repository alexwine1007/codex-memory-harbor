#!/usr/bin/env python3
"""Explicitly authorized file archiving; not a Runtime/backup-content adapter.

Copy bytes, verify SHA-256, retain a rollback file until independent validation,
then leave an absolute link at the original path. Never extracts archive contents.
"""
import argparse
from contextlib import contextmanager, ExitStack
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
    paths = path if isinstance(path, (list, tuple)) else [path]
    if not paths:
        return
    result = subprocess.run(["lsof", "-nP", "-Fp", *map(str, paths)], capture_output=True, timeout=10)
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


def archive_file(source, target, receipt, check_volume, check_handles=no_open_handles, keep_local=False, **options):
    item = dict(source=str(source), target=str(target), receipt=str(receipt), **options)
    try:
        return archive_batch([item], check_volume, check_handles, keep_local)['results'][0]
    except FileExistsError as exc:
        raise RuntimeError('来源或目标状态不符合安全条件') from exc


def _read(item):
    return item.get('read_record', previous_record)(Path(item['receipt']), Path(item['source']), Path(item['target']))


def _write(item, record):
    return item.get('write_record', append_receipt)(Path(item['receipt']), record)


def _backup(item):
    source = Path(item['source'])
    return source.with_name(source.name + item.get('backup_suffix', '.harbor-archive-rollback'))


def _validate(item):
    if item.get('validate'):
        item['validate']()


def _existing(item, check_volume, check_handles, keep_local):
    source, target, rollback = Path(item['source']), Path(item['target']), _backup(item)
    receipt = Path(item['receipt'])
    if receipt.is_symlink() or receipt.parent.resolve() != receipt.parent:
        raise RuntimeError('校验记录路径不安全，停止操作')
    identity = check_volume() or {}; record = _read(item)
    if (not record or os.readlink(source) != str(target) or target.is_symlink()
            or source.parent.resolve() != source.parent or target.parent.resolve() != target.parent
            or target.stat().st_size != record['bytes'] or digest(source) != record['sha256']
            or identity.get('volume_uuid') and record.get('volume_uuid') != identity['volume_uuid']):
        raise RuntimeError('已有链接缺少匹配的校验记录')
    if rollback.exists() and not keep_local:
        if rollback.is_symlink():
            raise RuntimeError('回滚副本不是本机普通文件，停止释放')
        check_handles(rollback); check_handles(target); _validate(item)
        check_volume()
        if (rollback.stat().st_size != record['bytes'] or digest(rollback) != record['sha256']
                or digest(target) != record['sha256']):
            raise RuntimeError('释放前内容发生变化，保留本地文件')
        rollback.unlink(); durable_directory(source.parent)
        _write(item, dict(record, status='local_entity_released'))
    return dict(record, status='already_verified')


def archive_batch(items, check_volume, check_handles=no_open_handles, keep_local=False, progress=None):
    """Runtime-neutral serial transactions, bounded phase batches, no safety-gate cache.

    Each path participates in all three *fresh* handle checkpoints. Small files
    share a single lsof invocation per phase; large files get their own batch.
    Copy, flush, target readback, link/rollback readback and pre-release readback
    remain per-file. No pipeline runs ahead after the first error.
    """
    if not items or len({str(row['source']) for row in items}) != len(items):
        raise ValueError('停泊清单为空或来源重复')
    if len({str(row['target']) for row in items}) != len(items):
        raise ValueError('停泊目标重复')
    started = time.perf_counter(); timings = {}; results = []; copied_bytes = 0
    total_bytes = sum(Path(row['source']).stat().st_size for row in items)
    @contextmanager
    def stage(name):
        if progress:
            progress(dict(phase=name, completed=len(results), total=len(items),
                          bytes=sum(row['bytes'] for row in results), total_bytes=total_bytes,
                          elapsed_seconds=time.perf_counter()-started))
        tick = time.perf_counter()
        try:
            yield
        finally:
            timings[name] = timings.get(name, 0) + time.perf_counter()-tick
            if progress:
                progress(dict(phase=name, completed=len(results), total=len(items),
                              bytes=sum(row['bytes'] for row in results), total_bytes=total_bytes,
                              elapsed_seconds=time.perf_counter()-started))
    def handles(paths):
        # Injected single-path guards remain compatible with the legacy API.
        if check_handles is no_open_handles:
            check_handles(paths)
        else:
            for path in paths:
                check_handles(path)
    pending = []
    def execute(chunk):
        nonlocal copied_bytes
        with ExitStack() as locks:
            for item in chunk:
                locks.enter_context(source_lock(Path(item['source'])))
            with stage('admission'):
                identity = check_volume() or {}
                for item in chunk:
                    _validate(item)
                    source, target, receipt = map(Path, (item['source'], item['target'], item['receipt']))
                    if (not source.is_absolute() or not target.is_absolute() or not source.is_file()
                            or source.is_symlink() or source.stat().st_nlink != 1
                            or source.parent.resolve() != source.parent):
                        raise RuntimeError('来源或目标状态不符合安全条件')
                    if target.exists() or target.is_symlink():
                        raise FileExistsError('目标已经存在，停止覆盖')
                    rollback = _backup(item)
                    if rollback.exists() or rollback.is_symlink():
                        raise RuntimeError('本地回滚副本已存在，停止操作')
                    if receipt.is_symlink() or receipt.parent.resolve() != receipt.parent:
                        raise RuntimeError('校验记录路径不安全，停止操作')
                    item['_before'] = signature(source)
                    if item.get('source_signature') and tuple(item['source_signature']) != item['_before']:
                        raise RuntimeError('来源与已确认方案不一致，停止操作')
                    safe_directory(target.parent)
                handles([Path(item['source']) for item in chunk])
            with stage('copy_flush'):
                for item in chunk:
                    hasher = hashlib.sha256()
                    with Path(item['source']).open('rb') as original, Path(item['target']).open('xb') as copied:
                        for block in iter(lambda: original.read(8*1024*1024), b''):
                            copied.write(block); hasher.update(block); copied_bytes += len(block)
                        copied.flush(); os.fsync(copied.fileno())
                    durable_directory(Path(item['target']).parent)
                    item['_hash'] = hasher.hexdigest()
                    if item.get('expected_hash') and item['_hash'] != item['expected_hash']:
                        raise RuntimeError('来源内容与已确认方案不一致，停止操作')
            with stage('target_verify'):
                check_volume()
                for item in chunk:
                    source, target = Path(item['source']), Path(item['target'])
                    if (signature(source) != item['_before'] or target.stat().st_size != item['_before'][2]
                            or digest(target) != item['_hash']):
                        raise RuntimeError('复制校验不通过，原文件未变更')
                handles([Path(item['source']) for item in chunk])
            changed = []; released = set()
            try:
                with stage('link_verify_receipt'):
                    for item in chunk:
                        _validate(item); source, target, rollback = Path(item['source']), Path(item['target']), _backup(item)
                        if signature(source) != item['_before']:
                            raise RuntimeError('来源发生变化，原文件未变更')
                        os.rename(source, rollback); changed.append(item)
                        source.symlink_to(target); durable_directory(source.parent)
                        check_volume()
                        if (os.readlink(source) != str(target) or source.stat().st_size != item['_before'][2]
                                or digest(source) != item['_hash'] or digest(rollback) != item['_hash']):
                            raise RuntimeError('独立复核失败')
                        record = dict(item.get('record_extra', {}), source=str(source), target=str(target),
                                      bytes=item['_before'][2], sha256=item['_hash'], status='verified_before_release',
                                      recorded_at=int(time.time()), **identity)
                        _write(item, record); item['_record'] = record
                with stage('release_verify'):
                    handles([path for item in chunk for path in (_backup(item), Path(item['target']))])
                    for item in chunk:
                        _validate(item); check_volume()
                        source, target, rollback = Path(item['source']), Path(item['target']), _backup(item)
                        record = item['_record']
                        if (not source.is_symlink() or os.readlink(source) != str(target)
                                or target.is_symlink() or rollback.is_symlink()
                                or target.parent.resolve() != target.parent
                                or target.stat().st_size != record['bytes'] or rollback.stat().st_size != record['bytes']
                                or digest(target) != record['sha256'] or digest(rollback) != record['sha256']):
                            raise RuntimeError('释放前内容发生变化，保留本地文件')
                        if not keep_local:
                            rollback.unlink(); released.add(str(source)); durable_directory(source.parent)
                            results.append(dict(record, status='local_entity_released'))
                            _write(item, dict(record, status='local_entity_released'))
                        else:
                            results.append(dict(record, status='verified_with_local_backup'))
                        released.add(str(source))  # A completed retained-backup transaction stays committed too.
            except BaseException:
                for item in reversed(changed):
                    source, rollback = Path(item['source']), _backup(item)
                    if str(source) in released:
                        continue  # Verified external-only transactions remain committed.
                    if source.is_symlink() and os.readlink(source) == item['target']:
                        source.unlink()
                    if not source.exists() and not source.is_symlink() and rollback.exists():
                        os.rename(rollback, source); durable_directory(source.parent)
                raise
    for original in items:
        item = dict(original); source = Path(item['source'])
        if source.is_symlink():
            if pending:
                execute(pending); pending = []
            with source_lock(source), stage('retry_verify'):
                _validate(item); results.append(_existing(item, check_volume, check_handles, keep_local))
            continue
        # <=32 paths and <=4 MiB per checkpoint group. Large files stand alone.
        size = source.stat().st_size
        if pending and (len(pending) >= 32 or sum(Path(row['source']).stat().st_size for row in pending)+size > 4*1024*1024):
            execute(pending); pending = []
        pending.append(item)
    if pending:
        execute(pending)
    elapsed = time.perf_counter()-started
    metrics = dict(elapsed_seconds=elapsed, stage_seconds=timings, bytes=total_bytes,
                   copied_bytes=copied_bytes, verified_bytes=sum(row['bytes'] for row in results),
                   files=len(results), mib_per_second=total_bytes/max(elapsed, 0.000001)/1048576,
                   efficiency=None, efficiency_note='未标定物理路径上限；此数值不是硬件效率')
    if progress:
        progress(dict(phase='complete', completed=len(results), total=len(items), bytes=metrics['verified_bytes'],
                      total_bytes=total_bytes, elapsed_seconds=elapsed, metrics=metrics))
    return {'results': results, 'metrics': metrics}




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
        from volume_probe import fresh_uuid
        if fresh_uuid(volume) != args.volume_uuid.upper():
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
    batch = []
    for number, source in enumerate(sources, 1):
        relative = rows[number - 1]["relative"] if project_plan else source.name
        if args.restore:
            record = restore_file(source, destination / relative, receipt, check_volume)
        else:
            item = dict(source=str(source), target=str(destination / relative), receipt=str(receipt))
            if rows:
                item['validate'] = lambda row=rows[number-1]: verify_planned_source(row)
            batch.append(item)
            continue
        print(json.dumps(record, ensure_ascii=False), flush=True)
    if batch:
        result = archive_batch(batch, check_volume, keep_local=project_plan and not args.release_local,
                               progress=lambda value: print(json.dumps(value, ensure_ascii=False), flush=True))
        for record in result['results']:
            print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
