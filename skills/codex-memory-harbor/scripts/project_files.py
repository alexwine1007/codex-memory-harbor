#!/usr/bin/env python3
"""只读项目文件方案。保留本机目录、工作文件和既有链接，只提出冷素材候选。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import time
import unicodedata

PLAN_SCHEMA = "memory-harbor-project-files-v1"
ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff",
                  ".mp4", ".mov", ".mkv", ".webm", ".mp3", ".wav", ".m4a",
                  ".aac", ".flac", ".srt", ".ass", ".psd", ".pdf"}
LOCAL_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".ssh", "secrets", "credentials"}
MAX_ENTRIES = 100000
REASONS = {"work_file": "工作文件保留本机", "linked": "保留既有链接", "too_new": "静置时间不足",
           "hardlink": "硬链接需单独处理", "special": "特殊文件需单独处理",
           "resource_fork": "资源分支需保留完整文件语义", "secret_name": "凭据相关文件保留本机",
           "name_collision": "目标文件系统名称冲突", "rollback": "已有本地回滚副本"}


def root_path(value: str) -> Path:
    path = Path(os.path.abspath(Path(value).expanduser()))
    if not path.is_dir() or path.is_symlink() or path.resolve() != path:
        raise ValueError("项目必须是可读取的本机真实目录")
    if path in (Path("/"), Path.home(), Path.home() / "Desktop", Path.home() / "Documents"):
        raise ValueError("不能把整个个人目录当成一个项目")
    if path.is_relative_to(Path("/Volumes")):
        raise ValueError("此方案用于本机项目，不递归扫描外置项目")
    return path


def secret_name(name: str) -> bool:
    name = name.lower()
    return (name.startswith(".env") or name in {"credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
            or name.endswith((".pem", ".key", ".p12", ".keychain", ".keychain-db")))


def asset_plan(value: str, min_age: float = 30, now: float | None = None) -> dict:
    root = root_path(value)
    if min_age < 0:
        raise ValueError("静置天数不能为负数")
    now = time.time() if now is None else now
    files, retained, groups, collisions, parked = [], {}, {}, {}, []
    scanned, local_bytes, linked_count, skipped_dirs = 0, 0, 0, 0
    stack = [root]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                scanned += 1
                if scanned > MAX_ENTRIES:
                    raise ValueError("项目文件过多，停止扫描；请选择更小的素材目录")
                path = Path(entry.path)
                relative = path.relative_to(root)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    if entry.name in LOCAL_DIRS or entry.name.startswith(".venv-"):
                        skipped_dirs += 1
                    else:
                        stack.append(path)
                    continue
                reason = None
                if stat.S_ISLNK(info.st_mode):
                    reason = "linked"; linked_count += 1
                    destination = Path(os.readlink(path))
                    # Listing an absolute link does not claim its target is a verified archive.
                    # Only the server's exact volume/path/receipt match makes it manageable.
                    if destination.is_absolute():
                        parked.append({"source": str(path), "relative": str(relative), "target": str(destination)})
                elif not stat.S_ISREG(info.st_mode):
                    reason = "special"
                else:
                    local_bytes += info.st_size
                    if secret_name(entry.name): reason = "secret_name"
                    elif entry.name.endswith((".offload-local-backup", ".harbor-archive-rollback")): reason = "rollback"
                    elif path.suffix.lower() not in ASSET_SUFFIXES: reason = "work_file"
                    elif info.st_nlink != 1: reason = "hardlink"
                    elif now - info.st_mtime < min_age * 86400: reason = "too_new"
                    elif hasattr(os, "listxattr") and "com.apple.ResourceFork" in os.listxattr(path): reason = "resource_fork"
                group = str(relative.parts[0]) if len(relative.parts) > 1 else "项目根目录"
                group_record = groups.setdefault(group, {"name": group, "bytes": 0, "candidate_bytes": 0, "candidate_count": 0})
                if stat.S_ISREG(info.st_mode): group_record["bytes"] += info.st_size
                if reason:
                    retained[reason] = retained.get(reason, 0) + 1
                    continue
                key = unicodedata.normalize("NFC", str(relative)).casefold()
                row = {"source": str(path), "relative": str(relative), "bytes": info.st_size,
                       "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
                       "inode": info.st_ino, "device": info.st_dev, "group": group}
                collisions.setdefault(key, []).append(row)
                files.append(row)
    duplicates = {row["source"] for rows in collisions.values() if len(rows) > 1 for row in rows}
    if duplicates:
        files = [row for row in files if row["source"] not in duplicates]
        retained["name_collision"] = len(duplicates)
    files.sort(key=lambda row: row["relative"])
    for row in files:
        group = groups[row["group"]]
        group["candidate_bytes"] += row["bytes"]; group["candidate_count"] += 1
    return {"schema": PLAN_SCHEMA, "project_root": str(root), "generated_at": int(now),
            "min_age": min_age, "count": len(files), "total_bytes": sum(row["bytes"] for row in files),
            "local_file_bytes": local_bytes, "linked_count": linked_count, "skipped_local_directories": skipped_dirs,
            "retained": [{"reason": key, "label": REASONS[key], "count": value} for key, value in sorted(retained.items())],
            "groups": sorted(groups.values(), key=lambda row: row["bytes"], reverse=True), "files": files, "parked_files": parked,
            "semantics": "保留本机目录与工作文件，逐文件建立原路径链接；不是整个活跃工作区外置"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root")
    parser.add_argument("--min-age", type=float, default=30)
    args = parser.parse_args()
    try:
        print(json.dumps(asset_plan(args.project_root, args.min_age), ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"项目方案未完成：{exc}\n")


if __name__ == "__main__":
    main()
