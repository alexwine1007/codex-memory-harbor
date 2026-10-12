#!/usr/bin/env python3
"""Memory Harbor：本地清点、安全停泊、验证恢复与桌面仪表盘。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import html
import json
import mimetypes
import os
from pathlib import Path
import plistlib
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
import re
import select
from collections import deque
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.4.6-beta.2"
DEFAULT_ARCHIVE = "Memory Harbor"
LEGACY_ARCHIVES = ("Codex Memory Harbor",)
CATALOG_SCHEMA_VERSION = 3
MANIFEST_SCHEMA_VERSION = 2
RECALL_EXTRACTION_VERSION = 1
RECALL_CHUNK_CHARS = 6000
RECALL_CHUNK_OVERLAP = 240
RECALL_MAX_FRAGMENTS_PER_SESSION = 5000
REASON_LABELS = {
    "unreadable": "记录不可读取",
    "main_task": "主任务受保护",
    "already_offloaded": "已经停泊",
    "drive_unavailable": "外置存储未连接",
    "too_new": "静置时间不足",
    "last_turn_incomplete": "最后一轮尚未完成",
    "priority_project": "所属项目已保护",
    "protected_session": "任务已设为长期保留",
}


class HarborError(RuntimeError):
    pass


def user_error(exc: Exception) -> tuple[str, str]:
    """Return a stable code and Chinese message without exposing raw system text."""
    if isinstance(exc, HarborError):
        return "harbor_error", str(exc)
    if isinstance(exc, PermissionError):
        return "permission_denied", "没有权限访问所需文件或存储设备"
    if isinstance(exc, FileNotFoundError):
        return "file_unavailable", "所需文件或存储位置当前不可用"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json", "读取的数据格式无效"
    if isinstance(exc, ValueError):
        return "invalid_value", "输入值或数据格式无效"
    if isinstance(exc, OSError):
        code = f"os_error_{exc.errno}" if exc.errno is not None else "os_error"
        return code, "本地文件操作未完成"
    return "unexpected_error", "操作未完成；本地数据未因本次失败被释放"


def config_path() -> Path:
    return Path(os.environ.get("CODEX_HARBOR_CONFIG", "~/.config/codex-memory-harbor/config.json")).expanduser()


def catalog_path(codex_home: Path) -> Path:
    override = os.environ.get("CODEX_HARBOR_CATALOG")
    return Path(override).expanduser() if override else codex_home / "memory-harbor" / "catalog.sqlite3"


def load_config() -> dict:
    path = config_path()
    if not path.is_file():
        return {"protected_projects": [], "protected_sessions": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        projects = value.get("protected_projects") or ([value["priority"]] if value.get("priority") else [])
        return {"protected_projects": [str(item) for item in projects if item], "protected_sessions": [str(item) for item in value.get("protected_sessions", []) if item]}
    except (OSError, ValueError, TypeError) as exc:
        raise HarborError("保护设置无法读取，请先修复设置；本次停止迁移") from exc


def parse_projects(value) -> list[str]:
    if isinstance(value, list):
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
    return list(dict.fromkeys(item.strip() for line in str(value or "").splitlines() for item in line.split(",") if item.strip()))


def save_config(protected_projects, protected_sessions=None) -> dict:
    path = config_path(); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    value = {"protected_projects": parse_projects(protected_projects), "protected_sessions": sorted(set(protected_sessions or [])), "updated_at": int(time.time())}
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return value


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def first_metadata(path: Path) -> dict:
    with path.open("rb") as stream:
        raw = stream.readline()
    data = json.loads(raw)
    payload = data.get("payload") or {}
    source = payload.get("source") or {}
    spawn = source.get("subagent", {}).get("thread_spawn", {}) if isinstance(source, dict) else {}
    return {
        "id": payload.get("id"),
        "parent_thread_id": payload.get("parent_thread_id"),
        "cwd": payload.get("cwd"),
        "timestamp": payload.get("timestamp"),
        "thread_source": payload.get("thread_source"),
        "agent_nickname": payload.get("agent_nickname") or spawn.get("agent_nickname"),
        "agent_path": payload.get("agent_path") or spawn.get("agent_path"),
    }


def last_turn_complete(path: Path, window: int = 128 * 1024) -> bool:
    size = path.stat().st_size
    with path.open("rb") as stream:
        stream.seek(max(0, size - window))
        chunk = stream.read()
    lines = chunk.splitlines()
    if size > window and lines:
        lines = lines[1:]
    for raw in reversed(lines):
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if data.get("type") != "event_msg":
            continue
        event_type = (data.get("payload") or {}).get("type")
        if event_type == "task_complete":
            return True
        if event_type == "task_started":
            return False
    if size > window and window < 2 * 1024 * 1024:
        return last_turn_complete(path, 2 * 1024 * 1024)
    return False


def local_allocated(path: Path) -> int:
    return os.lstat(path).st_blocks * 512


def open_handles(path: Path) -> int:
    try:
        result = subprocess.run(["lsof", "-nP", str(path)], capture_output=True, text=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HarborError("文件句柄检查未完成，停止停泊") from exc
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise HarborError("文件句柄检查失败，停止停泊")
    rows = [row for row in result.stdout.splitlines() if row.strip()]
    return max(0, len(rows) - 1)


def is_priority(cwd: str | None, priority) -> bool:
    if not cwd or not priority:
        return False
    for protected in parse_projects(priority):
        try:
            Path(cwd).expanduser().resolve().relative_to(Path(protected).expanduser().resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def lexical_session(path_value: str, codex_home: Path) -> tuple[Path, Path]:
    path = Path(os.path.abspath(Path(path_value).expanduser()))
    root = Path(os.path.abspath(codex_home / "sessions"))
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise HarborError(f"历史记录必须位于 {root} 下") from exc
    if path.parent.resolve() != path.parent or path.suffix != ".jsonl":
        raise HarborError("历史路径包含目录链接或不是 JSONL 文件")
    return path, relative


def mounted_volume(path_value: str) -> Path:
    volume = Path(path_value).expanduser().absolute()
    if volume.parent != Path("/Volumes") or volume.is_symlink():
        raise HarborError("必须选择 /Volumes 下的真实挂载卷")
    if not volume.is_dir() or not os.path.ismount(volume):
        raise HarborError(f"外置存储尚未挂载：{volume}")
    if not os.access(volume, os.W_OK):
        raise HarborError(f"外置存储不可写：{volume}")
    return volume


def volume_identity(volume: Path) -> dict:
    """Return a persistent macOS volume identity when Disk Arbitration exposes one."""
    identity = {"uuid": "", "device_identifier": "", "filesystem": ""}
    try:
        result = subprocess.run(
            ["diskutil", "info", "-plist", str(volume)],
            capture_output=True,
            check=False,
            timeout=3,
        )
        if result.returncode == 0 and result.stdout:
            value = plistlib.loads(result.stdout)
            identity["uuid"] = str(value.get("VolumeUUID") or value.get("APFSVolumeUUID") or value.get("MediaUUID") or "")
            identity["device_identifier"] = str(value.get("DeviceIdentifier") or "")
            identity["filesystem"] = str(value.get("FilesystemType") or value.get("FileSystemPersonality") or "")
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException, ValueError):
        pass
    if not identity["uuid"]:
        # This fallback is only a live-session hint. It is never presented as a
        # restart-persistent UUID and is not used to auto-repair links.
        try:
            identity["runtime_id"] = f"dev:{volume.stat().st_dev}"
        except OSError:
            identity["runtime_id"] = ""
    return identity


def available_volumes() -> list[dict]:
    result = []
    root = Path("/Volumes")
    if not root.exists():
        return result
    for volume in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not os.path.ismount(volume) or volume.name == "Macintosh HD":
            continue
        try:
            usage = shutil.disk_usage(volume)
            writable = os.access(volume, os.W_OK)
        except OSError:
            continue
        identity = volume_identity(volume)
        result.append({
            "path": str(volume), "name": volume.name, "free": usage.free,
            "free_h": human_bytes(usage.free), "writable": writable,
            "uuid": identity.get("uuid", ""), "runtime_id": identity.get("runtime_id", ""),
            "device_identifier": identity.get("device_identifier", ""),
            "filesystem": identity.get("filesystem", ""),
        })
    return result


def available_storage_targets(volumes: list[dict] | None = None) -> list[dict]:
    """Stable provider boundary: cloud backends can implement this contract later."""
    volumes = available_volumes() if volumes is None else volumes
    targets = [
        {
            "id": f"external:{volume['path']}",
            "provider": "external_volume",
            "location": volume["path"],
            "name": volume["name"],
            "available": volume["writable"],
            "free": volume["free"],
            "free_h": volume["free_h"],
            "volume_uuid": volume.get("uuid", ""),
            "device_identifier": volume.get("device_identifier", ""),
        }
        for volume in volumes
    ]
    targets.append({
        "id": "cloud:future",
        "provider": "cloud",
        "location": "",
        "name": "Memory Harbor Cloud",
        "available": False,
        "status": "future",
    })
    return targets


def load_project_catalog(codex_home: Path) -> dict:
    """Read Codex's local project assignment metadata, never conversation bodies."""
    empty = {"projects": {}, "assignments": {}, "projectless": set()}
    state_path = codex_home / ".codex-global-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return empty
    raw_projects = state.get("local-projects") or {}
    projects = {}
    if isinstance(raw_projects, dict):
        for project_id, value in raw_projects.items():
            if not isinstance(value, dict):
                continue
            roots = [str(path) for path in value.get("rootPaths") or [] if path]
            projects[str(project_id)] = {
                "id": str(project_id),
                "name": str(value.get("name") or (Path(roots[0]).name if roots else "未命名项目")),
                "roots": roots,
            }
    assignments = {}
    raw_assignments = state.get("thread-project-assignments") or {}
    if isinstance(raw_assignments, dict):
        for thread_id, value in raw_assignments.items():
            if isinstance(value, dict) and value.get("projectKind") == "local" and value.get("projectId"):
                assignments[str(thread_id)] = str(value["projectId"])
    projectless = {str(value) for value in (state.get("projectless-thread-ids") or []) if value}
    return {"projects": projects, "assignments": assignments, "projectless": projectless}


def state_database(codex_home: Path) -> Path | None:
    candidates = list(codex_home.glob("state_*.sqlite"))
    try:
        return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None
    except OSError:
        return None


def read_only_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{urllib.parse.quote(str(path))}?mode=ro", uri=True, timeout=1)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def clean_index_text(value: str | None, maximum: int | None = None) -> str:
    text = html.unescape(str(value or ""))
    match = re.search(r"<input>(.*?)</input>", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        text = match.group(1)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if maximum and len(text) > maximum:
        text = text[: maximum - 1].rstrip() + "…"
    return text


def compact_task_title(value: str | None) -> str:
    text = clean_index_text(value)
    text = re.split(r"\s+\[\d+\]\s+(?:user|assistant):", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    text = re.sub(r"^(这是|请你|请|任务[:：]\s*)", "", text).strip()
    sentence = re.split(r"(?<=[。！？!?])\s*", text, maxsplit=1)[0] if text else ""
    return clean_index_text(sentence, 72).rstrip("。！？!? ")


def agent_task_title(agent_path: str | None) -> str:
    leaf = str(agent_path or "").strip().rstrip("/").split("/")[-1]
    return clean_index_text(leaf.replace("_", " ").replace("-", " "), 72)


def load_thread_catalog(codex_home: Path) -> dict:
    """Load display titles from Codex's index without reading session bodies."""
    database = state_database(codex_home)
    if not database:
        return {"by_id": {}, "by_path": {}}
    try:
        with read_only_database(database) as connection:
            rows = connection.execute("SELECT id, rollout_path, title, agent_nickname FROM threads").fetchall()
    except (OSError, sqlite3.Error):
        return {"by_id": {}, "by_path": {}}
    by_id, by_path = {}, {}
    for row in rows:
        value = {"id": str(row["id"]), "title": compact_task_title(row["title"]), "agent_nickname": str(row["agent_nickname"] or "").strip()}
        by_id[value["id"]] = value
        if row["rollout_path"]:
            by_path[str(Path(row["rollout_path"]).expanduser().absolute())] = value
    return {"by_id": by_id, "by_path": by_path}


def open_catalog(codex_home: Path) -> sqlite3.Connection:
    path = catalog_path(codex_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS harbor_items (
            source_path TEXT PRIMARY KEY,
            thread_id TEXT,
            parent_id TEXT,
            title TEXT NOT NULL DEFAULT '',
            project_id TEXT,
            project_name TEXT,
            project_path TEXT,
            cwd TEXT NOT NULL DEFAULT '',
            agent_path TEXT NOT NULL DEFAULT '',
            timestamp TEXT,
            kind TEXT NOT NULL DEFAULT '',
            logical INTEGER NOT NULL DEFAULT 0,
            source_sha256 TEXT NOT NULL DEFAULT '',
            linked INTEGER NOT NULL DEFAULT 0,
            source_present INTEGER NOT NULL DEFAULT 0,
            target_path TEXT,
            target_available INTEGER NOT NULL DEFAULT 0,
            volume_uuid TEXT NOT NULL DEFAULT '',
            volume_name TEXT NOT NULL DEFAULT '',
            archive_relative TEXT NOT NULL DEFAULT '',
            manifest_path TEXT NOT NULL DEFAULT '',
            last_seen_at INTEGER NOT NULL DEFAULT 0,
            manifest_recorded_at INTEGER NOT NULL DEFAULT 0
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS harbor_items_thread_id ON harbor_items(thread_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS harbor_items_project_id ON harbor_items(project_id)")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS harbor_fragments (
            fragment_id TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            thread_id TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            source_line INTEGER NOT NULL DEFAULT 0,
            ordinal INTEGER NOT NULL DEFAULT 0,
            timestamp TEXT,
            indexed_at INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(source_path) REFERENCES harbor_items(source_path) ON DELETE CASCADE
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS harbor_fragments_source_path ON harbor_fragments(source_path)")
    connection.execute("CREATE INDEX IF NOT EXISTS harbor_fragments_thread_id ON harbor_fragments(thread_id)")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS harbor_recall_state (
            source_path TEXT PRIMARY KEY,
            source_sha256 TEXT NOT NULL,
            extraction_version INTEGER NOT NULL,
            fragment_count INTEGER NOT NULL DEFAULT 0,
            indexed_at INTEGER NOT NULL DEFAULT 0
        )
    """)
    connection.execute("CREATE TABLE IF NOT EXISTS harbor_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute(
        "INSERT OR REPLACE INTO harbor_meta(key, value) VALUES ('schema_version', ?)",
        (str(CATALOG_SCHEMA_VERSION),),
    )
    tokenizer_row = connection.execute("SELECT value FROM harbor_meta WHERE key='fts_tokenizer'").fetchone()
    tokenizer = tokenizer_row[0] if tokenizer_row and tokenizer_row[0] in ("trigram", "unicode61") else None
    if tokenizer is None:
        try:
            connection.execute("""
                CREATE VIRTUAL TABLE harbor_fts USING fts5(
                    source_path UNINDEXED, thread_id, title, project_name, cwd, agent_path,
                    tokenize='trigram'
                )
            """)
            tokenizer = "trigram"
        except sqlite3.Error:
            connection.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS harbor_fts USING fts5(
                    source_path UNINDEXED, thread_id, title, project_name, cwd, agent_path
                )
            """)
            tokenizer = "unicode61"
        connection.execute("INSERT OR REPLACE INTO harbor_meta(key, value) VALUES ('fts_tokenizer', ?)", (tokenizer,))
    elif tokenizer == "trigram":
        connection.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS harbor_fts USING fts5(
                source_path UNINDEXED, thread_id, title, project_name, cwd, agent_path,
                tokenize='trigram'
            )
        """)
    else:
        connection.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS harbor_fts USING fts5(
                source_path UNINDEXED, thread_id, title, project_name, cwd, agent_path
            )
        """)
    fragment_tokenizer_row = connection.execute("SELECT value FROM harbor_meta WHERE key='fragment_fts_tokenizer'").fetchone()
    fragment_tokenizer = fragment_tokenizer_row[0] if fragment_tokenizer_row and fragment_tokenizer_row[0] in ("trigram", "unicode61") else None
    if fragment_tokenizer is None:
        try:
            connection.execute("""
                CREATE VIRTUAL TABLE harbor_fragments_fts USING fts5(
                    source_path UNINDEXED, fragment_id UNINDEXED, role, content,
                    tokenize='trigram'
                )
            """)
            fragment_tokenizer = "trigram"
        except sqlite3.Error:
            connection.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS harbor_fragments_fts USING fts5(
                    source_path UNINDEXED, fragment_id UNINDEXED, role, content
                )
            """)
            fragment_tokenizer = "unicode61"
        connection.execute(
            "INSERT OR REPLACE INTO harbor_meta(key, value) VALUES ('fragment_fts_tokenizer', ?)",
            (fragment_tokenizer,),
        )
    elif fragment_tokenizer == "trigram":
        connection.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS harbor_fragments_fts USING fts5(
                source_path UNINDEXED, fragment_id UNINDEXED, role, content,
                tokenize='trigram'
            )
        """)
    else:
        connection.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS harbor_fragments_fts USING fts5(
                source_path UNINDEXED, fragment_id UNINDEXED, role, content
            )
        """)
    return connection


@contextmanager
def managed_catalog(codex_home: Path):
    connection = open_catalog(codex_home)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


@contextmanager
def read_catalog(codex_home: Path):
    """Open the compact catalog without creating files, WALs, or schema writes."""
    path = catalog_path(codex_home)
    if not path.is_file():
        yield None
        return
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        yield connection
    finally:
        connection.close()


def catalog_upsert(connection: sqlite3.Connection, record: dict) -> None:
    source_path = str(record.get("source_path") or record.get("source") or record.get("path") or "")
    if not source_path:
        return
    existing = connection.execute("SELECT * FROM harbor_items WHERE source_path = ?", (source_path,)).fetchone()
    old = dict(existing) if existing else {}
    def keep(name, default=""):
        value = record.get(name)
        return value if value not in (None, "") else old.get(name, default)
    values = {
        "source_path": source_path,
        "thread_id": keep("thread_id", record.get("id") or ""),
        "parent_id": keep("parent_id"),
        "title": keep("title"),
        "project_id": keep("project_id"),
        "project_name": keep("project_name"),
        "project_path": keep("project_path"),
        "cwd": keep("cwd"),
        "agent_path": keep("agent_path"),
        "timestamp": keep("timestamp"),
        "kind": keep("kind"),
        "logical": int(record.get("logical", record.get("bytes", old.get("logical", 0))) or 0),
        "source_sha256": keep("source_sha256", record.get("sha256") or ""),
        "linked": int(bool(record.get("linked", old.get("linked", False)))),
        "source_present": int(bool(record.get("source_present", old.get("source_present", False)))),
        "target_path": keep("target_path", record.get("target") or record.get("destination") or ""),
        "target_available": int(bool(record.get("target_available", record.get("target_exists", old.get("target_available", False))))),
        "volume_uuid": keep("volume_uuid"),
        "volume_name": keep("volume_name"),
        "archive_relative": keep("archive_relative"),
        "manifest_path": keep("manifest_path", record.get("manifest") or ""),
        "last_seen_at": int(record.get("last_seen_at", int(time.time())) or 0),
        "manifest_recorded_at": int(record.get("manifest_recorded_at", record.get("recorded_at", old.get("manifest_recorded_at", 0))) or 0),
    }
    columns = list(values)
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{column}=excluded.{column}" for column in columns if column != "source_path")
    connection.execute(
        f"INSERT INTO harbor_items ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(source_path) DO UPDATE SET {updates}",
        tuple(values[column] for column in columns),
    )
    connection.execute("DELETE FROM harbor_fts WHERE source_path = ?", (source_path,))
    connection.execute(
        "INSERT INTO harbor_fts(source_path, thread_id, title, project_name, cwd, agent_path) VALUES (?, ?, ?, ?, ?, ?)",
        (source_path, values["thread_id"], values["title"], values["project_name"], values["cwd"], values["agent_path"]),
    )


def catalog_update_from_scan(codex_home: Path, sessions: list[dict], volumes: list[dict] | None = None) -> dict:
    now = int(time.time())
    volumes = available_volumes() if volumes is None else volumes
    with managed_catalog(codex_home) as connection:
        connection.execute("UPDATE harbor_items SET source_present = 0")
        mounted_uuids = [str(volume.get("uuid")) for volume in volumes if volume.get("uuid")]
        if mounted_uuids:
            placeholders = ",".join("?" for _ in mounted_uuids)
            connection.execute(
                f"UPDATE harbor_items SET target_available = 0 WHERE volume_uuid != '' AND volume_uuid NOT IN ({placeholders})",
                tuple(mounted_uuids),
            )
        else:
            connection.execute("UPDATE harbor_items SET target_available = 0 WHERE volume_uuid != ''")
        for item in sessions:
            target = str(item.get("target") or "")
            volume = next((value for value in volumes if target == value["path"] or target.startswith(value["path"] + os.sep)), None)
            archive_relative = ""
            if volume and target:
                try:
                    archive_relative = str(Path(target).relative_to(Path(volume["path"])))
                except ValueError:
                    pass
            catalog_upsert(connection, {
                "source_path": item["path"], "thread_id": item.get("id"),
                "parent_id": item.get("parent_id"), "title": item.get("title"),
                "project_id": item.get("project_id"), "project_name": item.get("project_name"),
                "project_path": item.get("project_path"), "cwd": item.get("cwd"),
                "agent_path": item.get("agent_path"), "timestamp": item.get("timestamp"),
                "kind": item.get("kind"), "logical": item.get("logical"),
                "linked": item.get("linked"), "source_present": True,
                "target_path": item.get("target"), "target_available": item.get("target_exists"),
                "volume_uuid": volume.get("uuid", "") if volume else "",
                "volume_name": volume.get("name", "") if volume else "",
                "archive_relative": archive_relative,
                "last_seen_at": now,
            })
        count = connection.execute("SELECT COUNT(*) FROM harbor_items").fetchone()[0]
        fragment_row = connection.execute(
            "SELECT COUNT(*) AS fragments, COUNT(DISTINCT source_path) AS sessions FROM harbor_fragments"
        ).fetchone()
    return {
        "path": str(catalog_path(codex_home)), "items": count, "updated_at": now,
        "recall_fragments": int(fragment_row["fragments"] or 0),
        "recall_sessions": int(fragment_row["sessions"] or 0),
    }


def catalog_search(codex_home: Path, query: str, limit: int = 20) -> list[dict]:
    query = clean_index_text(query, 300)
    if not query:
        return []
    limit = max(1, min(int(limit), 100))
    with read_catalog(codex_home) as connection:
        if connection is None:
            return []
        try:
            phrase = '"' + query.replace('"', '""') + '"'
            rows = connection.execute("""
                SELECT i.*, bm25(harbor_fts) AS score
                FROM harbor_fts JOIN harbor_items i USING(source_path)
                WHERE harbor_fts MATCH ?
                ORDER BY score, i.last_seen_at DESC LIMIT ?
            """, (phrase, limit)).fetchall()
        except sqlite3.Error:
            rows = []
        if not rows:
            needle = f"%{query}%"
            rows = connection.execute("""
                SELECT *, 0.0 AS score FROM harbor_items
                WHERE title LIKE ? OR project_name LIKE ? OR cwd LIKE ?
                   OR thread_id LIKE ? OR agent_path LIKE ?
                ORDER BY last_seen_at DESC LIMIT ?
            """, (needle, needle, needle, needle, needle, limit)).fetchall()
    return [dict(row) for row in rows]


def catalog_status(codex_home: Path) -> dict:
    with managed_catalog(codex_home) as connection:
        row = connection.execute("""
            SELECT COUNT(*) AS items,
                   SUM(source_present) AS present,
                   SUM(linked) AS linked,
                   SUM(target_available) AS targets_available,
                   MAX(last_seen_at) AS updated_at
            FROM harbor_items
        """).fetchone()
        tokenizer = connection.execute("SELECT value FROM harbor_meta WHERE key='fts_tokenizer'").fetchone()
        fragment_row = connection.execute(
            "SELECT COUNT(*) AS fragments, COUNT(DISTINCT source_path) AS sessions FROM harbor_fragments"
        ).fetchone()
        fragment_tokenizer = connection.execute(
            "SELECT value FROM harbor_meta WHERE key='fragment_fts_tokenizer'"
        ).fetchone()
    return {
        "path": str(catalog_path(codex_home)), "schema_version": CATALOG_SCHEMA_VERSION,
        "items": int(row["items"] or 0), "present": int(row["present"] or 0),
        "linked": int(row["linked"] or 0), "targets_available": int(row["targets_available"] or 0),
        "updated_at": int(row["updated_at"] or 0), "fts_tokenizer": tokenizer[0] if tokenizer else "unknown",
        "recall_fragments": int(fragment_row["fragments"] or 0),
        "recall_sessions": int(fragment_row["sessions"] or 0),
        "fragment_fts_tokenizer": fragment_tokenizer[0] if fragment_tokenizer else "unknown",
    }


SENSITIVE_PATTERNS = (
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{12,}\b", re.IGNORECASE),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\b\s*[:=]\s*([^\s,;]{6,})"),
)
INJECTED_CONTEXT_TAGS = (
    "environment_context", "in-app-browser-context", "app-context", "permissions",
    "skills_instructions", "apps_instructions", "plugins_instructions", "recommended_plugins",
)


def redact_sensitive_text(value: str) -> str:
    text = value
    for pattern in SENSITIVE_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


def clean_recall_text(value: str) -> str:
    text = html.unescape(str(value or ""))
    for tag in INJECTED_CONTEXT_TAGS:
        text = re.sub(rf"<{re.escape(tag)}\b[^>]*>.*?</{re.escape(tag)}>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return redact_sensitive_text(text)


def payload_text(payload: dict) -> str:
    content = payload.get("content") or []
    if isinstance(content, str):
        return content
    parts = []
    for item in content if isinstance(content, list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("type") in ("input_text", "output_text", "text") and item.get("text"):
            parts.append(str(item["text"]))
    return "\n".join(parts)


def chunk_recall_text(text: str):
    if len(text) <= RECALL_CHUNK_CHARS:
        yield text
        return
    step = RECALL_CHUNK_CHARS - RECALL_CHUNK_OVERLAP
    for start in range(0, len(text), step):
        chunk = text[start:start + RECALL_CHUNK_CHARS].strip()
        if chunk:
            yield chunk
        if start + RECALL_CHUNK_CHARS >= len(text):
            break


def recall_candidate_line(line: str) -> bool:
    """Reject large tool-output lines before JSON decoding."""
    head = line[:8192]
    return bool(
        re.search(r'"type"\s*:\s*"(?:response_item|event_msg)"', head)
        and re.search(r'"type"\s*:\s*"(?:message|agent_message)"', head)
    )


def recall_fragments_from_session(path: Path) -> list[dict]:
    """Extract task-specific human/assistant evidence while excluding tool and inherited history."""
    meta = first_metadata(path)
    thread_id = str(meta.get("id") or "")
    agent_path = str(meta.get("agent_path") or "")
    if meta.get("parent_thread_id") and not agent_path:
        # Legacy child/fork records can contain inherited parent turns without a
        # trustworthy task boundary. Metadata discovery is safer than false recall.
        return []
    started = not bool(agent_path)
    raw_fragments = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, 1):
            if not recall_candidate_line(line):
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = value.get("payload") or {}
            if agent_path and not started:
                if value.get("type") != "response_item" or payload.get("type") != "agent_message":
                    continue
                recipient = str(payload.get("recipient") or "")
                marker = payload_text(payload)
                if recipient != agent_path or "Message Type: NEW_TASK" not in marker:
                    continue
                started = True
                match = re.search(r"<input>(.*?)</input>", marker, flags=re.DOTALL | re.IGNORECASE)
                if match:
                    raw_fragments.append(("instruction", match.group(1), line_number, value.get("timestamp")))
                continue
            if not started:
                continue
            if agent_path:
                if value.get("type") == "event_msg" and payload.get("type") == "agent_message":
                    raw_fragments.append(("assistant", str(payload.get("message") or ""), line_number, value.get("timestamp")))
                continue
            if value.get("type") != "response_item" or payload.get("type") != "message":
                continue
            role = str(payload.get("role") or "")
            if role in ("user", "assistant"):
                raw_fragments.append((role, payload_text(payload), line_number, value.get("timestamp")))
    fragments = []
    ordinal = 0
    for role, raw_text, line_number, timestamp in raw_fragments:
        cleaned = clean_recall_text(raw_text)
        if not cleaned:
            continue
        for chunk in chunk_recall_text(cleaned):
            ordinal += 1
            digest = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
            fragment_id = hashlib.sha256(f"{path.absolute()}\0{line_number}\0{ordinal}\0{digest}".encode()).hexdigest()
            fragments.append({
                "fragment_id": fragment_id, "source_path": str(path.absolute()), "thread_id": thread_id,
                "role": role, "content": chunk, "content_sha256": digest,
                "source_line": line_number, "ordinal": ordinal, "timestamp": timestamp,
            })
            if len(fragments) >= RECALL_MAX_FRAGMENTS_PER_SESSION:
                return fragments
    return fragments


def index_session_memory(path_value: str, codex_home: Path, expected_sha256: str | None = None) -> dict:
    source, _ = lexical_session(path_value, codex_home)
    if not source.exists():
        raise HarborError("历史证据当前不可用；请重新连接对应存储后再建立索引")
    metadata = first_metadata(source)
    with managed_catalog(codex_home) as connection:
        item = connection.execute("SELECT source_sha256 FROM harbor_items WHERE source_path = ?", (str(source),)).fetchone()
        state = connection.execute("SELECT * FROM harbor_recall_state WHERE source_path = ?", (str(source),)).fetchone()
    source_digest = str(expected_sha256 or (item["source_sha256"] if item else "") or sha256(source))
    if state and state["source_sha256"] == source_digest and int(state["extraction_version"]) == RECALL_EXTRACTION_VERSION:
        return {
            "source": str(source), "thread_id": str(metadata.get("id") or ""),
            "fragments": int(state["fragment_count"]),
            "metadata_only": bool(metadata.get("parent_thread_id") and not metadata.get("agent_path")),
            "indexed_at": int(state["indexed_at"]), "unchanged": True,
        }
    fragments = recall_fragments_from_session(source)
    now = int(time.time())
    with managed_catalog(codex_home) as connection:
        connection.execute("DELETE FROM harbor_fragments_fts WHERE source_path = ?", (str(source),))
        connection.execute("DELETE FROM harbor_fragments WHERE source_path = ?", (str(source),))
        for fragment in fragments:
            connection.execute("""
                INSERT INTO harbor_fragments(
                    fragment_id, source_path, thread_id, role, content, content_sha256,
                    source_line, ordinal, timestamp, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fragment["fragment_id"], fragment["source_path"], fragment["thread_id"],
                fragment["role"], fragment["content"], fragment["content_sha256"],
                fragment["source_line"], fragment["ordinal"], fragment["timestamp"], now,
            ))
            connection.execute(
                "INSERT INTO harbor_fragments_fts(source_path, fragment_id, role, content) VALUES (?, ?, ?, ?)",
                (fragment["source_path"], fragment["fragment_id"], fragment["role"], fragment["content"]),
            )
        connection.execute("""
            INSERT INTO harbor_recall_state(source_path, source_sha256, extraction_version, fragment_count, indexed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_path) DO UPDATE SET
                source_sha256=excluded.source_sha256,
                extraction_version=excluded.extraction_version,
                fragment_count=excluded.fragment_count,
                indexed_at=excluded.indexed_at
        """, (str(source), source_digest, RECALL_EXTRACTION_VERSION, len(fragments), now))
    return {
        "source": str(source), "thread_id": str(metadata.get("id") or ""),
        "fragments": len(fragments),
        "metadata_only": bool(metadata.get("parent_thread_id") and not metadata.get("agent_path")),
        "indexed_at": now, "unchanged": False,
    }


def excerpt_for_query(content: str, query: str, maximum: int = 260) -> str:
    compact = re.sub(r"\s+", " ", content).strip()
    index = compact.casefold().find(query.casefold())
    if index < 0:
        return compact[:maximum] + ("…" if len(compact) > maximum else "")
    start = max(0, index - maximum // 3)
    end = min(len(compact), start + maximum)
    prefix = "…" if start else ""
    suffix = "…" if end < len(compact) else ""
    return prefix + compact[start:end] + suffix


def recall_search(codex_home: Path, query: str, limit: int = 20) -> list[dict]:
    query = clean_index_text(query, 300)
    if not query:
        return []
    limit = max(1, min(int(limit), 100))
    with read_catalog(codex_home) as connection:
        if connection is None:
            return []
        try:
            phrase = '"' + query.replace('"', '""') + '"'
            rows = connection.execute("""
                SELECT i.*, f.fragment_id, f.role AS match_role, f.content AS match_content,
                       f.source_line AS match_source_line, f.timestamp AS match_timestamp,
                       bm25(harbor_fragments_fts) AS score
                FROM harbor_fragments_fts x
                JOIN harbor_fragments f ON f.fragment_id = x.fragment_id
                JOIN harbor_items i ON i.source_path = f.source_path
                WHERE harbor_fragments_fts MATCH ?
                ORDER BY score, COALESCE(f.timestamp, i.timestamp) DESC LIMIT ?
            """, (phrase, limit * 3)).fetchall()
        except sqlite3.Error:
            rows = []
        if not rows:
            needle = f"%{query}%"
            rows = connection.execute("""
                SELECT i.*, f.fragment_id, f.role AS match_role, f.content AS match_content,
                       f.source_line AS match_source_line, f.timestamp AS match_timestamp, 0.0 AS score
                FROM harbor_fragments f JOIN harbor_items i USING(source_path)
                WHERE f.content LIKE ? ORDER BY COALESCE(f.timestamp, i.timestamp) DESC LIMIT ?
            """, (needle, limit * 3)).fetchall()
    combined = []
    seen = set()
    for row in rows:
        item = dict(row)
        source = item["source_path"]
        if source in seen:
            continue
        seen.add(source)
        content = item.pop("match_content", "")
        item["match_excerpt"] = excerpt_for_query(content, query)
        item["match_kind"] = "content"
        item["evidence_untrusted"] = True
        combined.append(item)
        if len(combined) >= limit:
            return combined
    for item in catalog_search(codex_home, query, limit):
        source = item["source_path"]
        if source in seen:
            continue
        item["match_kind"] = "metadata"
        item["evidence_untrusted"] = True
        combined.append(item)
        seen.add(source)
        if len(combined) >= limit:
            break
    return combined


def build_recall_index(codex_home: Path, paths: list[str] | None = None, linked_only: bool = True) -> dict:
    config = load_config()
    snapshot = scan(codex_home, 30, config["protected_projects"], config["protected_sessions"])
    requested = set(paths or [])
    candidates = [
        item for item in snapshot["sessions"]
        if (not requested or item["path"] in requested)
        and item["kind"] == "child"
        and (item["linked"] if linked_only and not requested else True)
        and (item["target_exists"] or not item["linked"])
    ]
    results, errors = [], []
    for item in candidates:
        try:
            results.append(index_session_memory(item["path"], codex_home))
        except (HarborError, OSError, ValueError, json.JSONDecodeError) as exc:
            code, message = user_error(exc)
            errors.append({"source": item["path"], "error_code": code, "error": message})
    return {
        "sessions": len(results), "fragments": sum(item["fragments"] for item in results),
        "unchanged": sum(bool(item.get("unchanged")) for item in results),
        "errors": errors, "results": results,
    }


def clear_recall_index(codex_home: Path, paths: list[str] | None = None) -> dict:
    with managed_catalog(codex_home) as connection:
        if paths:
            normalized = [str(lexical_session(path, codex_home)[0]) for path in paths]
            placeholders = ",".join("?" for _ in normalized)
            before = connection.execute(
                f"SELECT COUNT(*) FROM harbor_fragments WHERE source_path IN ({placeholders})", normalized
            ).fetchone()[0]
            connection.execute(f"DELETE FROM harbor_fragments_fts WHERE source_path IN ({placeholders})", normalized)
            connection.execute(f"DELETE FROM harbor_fragments WHERE source_path IN ({placeholders})", normalized)
            connection.execute(f"DELETE FROM harbor_recall_state WHERE source_path IN ({placeholders})", normalized)
        else:
            before = connection.execute("SELECT COUNT(*) FROM harbor_fragments").fetchone()[0]
            connection.execute("DELETE FROM harbor_fragments_fts")
            connection.execute("DELETE FROM harbor_fragments")
            connection.execute("DELETE FROM harbor_recall_state")
    return {"cleared_fragments": int(before), "paths": len(paths or [])}


def manifest_relative(record: dict, archive_name: str) -> str:
    relative = str(record.get("archive_relative") or "").lstrip("/")
    if relative:
        return relative
    destination = Path(str(record.get("destination") or record.get("target") or ""))
    parts = destination.parts
    try:
        index = parts.index(archive_name)
        return str(Path(*parts[index:]))
    except ValueError:
        return ""


def import_mounted_manifests(codex_home: Path, volumes: list[dict], archive_name: str = DEFAULT_ARCHIVE) -> int:
    """Merge external manifests into the rebuildable local catalog."""
    imported = 0
    thread_catalog = load_thread_catalog(codex_home)
    project_catalog = load_project_catalog(codex_home)
    with managed_catalog(codex_home) as connection:
        archive_names = tuple(dict.fromkeys((archive_name, *LEGACY_ARCHIVES)))
        for volume in volumes:
            for manifest_archive_name in archive_names:
                manifest = Path(volume["path"]) / manifest_archive_name / "manifests" / "offload_manifest.jsonl"
                if not manifest.is_file():
                    continue
                try:
                    lines = manifest.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                for line in lines:
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    source = str(raw.get("source") or "")
                    relative = manifest_relative(raw, manifest_archive_name)
                    if not source or not relative:
                        continue
                    try:
                        lexical_session(source, codex_home)
                    except HarborError:
                        # A removable disk may contain manifests from several Macs
                        # or CODEX_HOME roots. Never merge another root into this one.
                        continue
                    target = Path(volume["path"]) / relative
                    item = {
                        "path": source, "id": raw.get("id"), "parent_id": raw.get("parent_id"),
                        "cwd": raw.get("cwd") or "", "agent_path": raw.get("agent_path") or "",
                        "timestamp": raw.get("timestamp"), "kind": raw.get("kind") or "child",
                    }
                    attach_thread_title(item, thread_catalog)
                    attach_project(item, project_catalog)
                    catalog_upsert(connection, {
                        "source_path": source, "thread_id": item.get("id"), "parent_id": item.get("parent_id"),
                        "title": raw.get("title") or item.get("title"), "project_id": raw.get("project_id") or item.get("project_id"),
                        "project_name": raw.get("project_name") or item.get("project_name"),
                        "project_path": raw.get("project_path") or item.get("project_path"),
                        "cwd": item.get("cwd"), "agent_path": item.get("agent_path"), "timestamp": item.get("timestamp"),
                        "kind": item.get("kind"), "logical": raw.get("bytes", 0), "source_sha256": raw.get("sha256"),
                        "linked": Path(source).is_symlink(), "source_present": Path(source).exists() or Path(source).is_symlink(),
                        "target_path": str(target), "target_available": target.is_file(),
                        "volume_uuid": raw.get("volume_uuid") or volume.get("uuid", ""),
                        "volume_name": raw.get("volume_name") or volume.get("name", ""),
                        "archive_relative": relative, "manifest_path": str(manifest),
                        "manifest_recorded_at": raw.get("recorded_at", 0),
                    })
                    imported += 1
    return imported


def repair_links_by_volume_identity(codex_home: Path, volumes: list[dict]) -> list[dict]:
    """Repair broken absolute links only after UUID and content hash both match."""
    mounted = {str(volume.get("uuid")): volume for volume in volumes if volume.get("uuid")}
    repaired = []
    if not mounted or not catalog_path(codex_home).is_file():
        return repaired
    with managed_catalog(codex_home) as connection:
        rows = connection.execute("""
            SELECT * FROM harbor_items
            WHERE linked = 1 AND volume_uuid != '' AND archive_relative != '' AND source_sha256 != ''
        """).fetchall()
        for row in rows:
            source = Path(row["source_path"])
            if not source.is_symlink() or source.exists():
                continue
            volume = mounted.get(str(row["volume_uuid"]))
            if not volume:
                continue
            target = Path(volume["path"]) / row["archive_relative"]
            try:
                if not target.is_file() or target.stat().st_size != int(row["logical"] or 0):
                    continue
                if sha256(target) != row["source_sha256"]:
                    continue
                temporary = source.with_name(source.name + ".harbor-link-temp")
                temporary.unlink(missing_ok=True)
                temporary.symlink_to(target)
                os.replace(temporary, source)
                connection.execute(
                    "UPDATE harbor_items SET target_path=?, target_available=1, volume_name=?, last_seen_at=? WHERE source_path=?",
                    (str(target), volume.get("name", ""), int(time.time()), str(source)),
                )
                repaired.append({"source": str(source), "target": str(target), "volume_uuid": row["volume_uuid"]})
            except OSError:
                continue
    return repaired


def rebuild_catalog(codex_home: Path, min_age: float = 30, priority=None, protected_sessions=None) -> dict:
    path = catalog_path(codex_home)
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    result = scan(codex_home, min_age, priority, protected_sessions)
    return {"catalog": result["catalog"], "sessions_scanned": len(result["sessions"]), "rebuilt": True}


def attach_thread_title(item: dict, catalog: dict) -> None:
    thread = catalog["by_id"].get(str(item.get("id") or "")) or catalog["by_path"].get(str(Path(item["path"]).absolute()))
    indexed = thread["title"] if thread and thread.get("title") else None
    generic = indexed and indexed.strip().lower() in {"hello", "hi", "你好"}
    item["title"] = agent_task_title(item.get("agent_path")) if generic and item.get("agent_path") else indexed


def indexed_rollout_path(codex_home: Path, thread_id: str, rollout_value: str | None) -> Path:
    candidate = Path(str(rollout_value or "")).expanduser().absolute()
    if rollout_value:
        try:
            lexical_session(str(candidate), codex_home)
            if candidate.exists() or candidate.is_symlink():
                if first_metadata(candidate).get("id") == thread_id:
                    return candidate
        except (HarborError, OSError, ValueError, json.JSONDecodeError):
            pass
    for path in (codex_home / "sessions").rglob(f"*{thread_id}*.jsonl"):
        try:
            if first_metadata(path).get("id") == thread_id:
                return path
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    raise HarborError("任务记录文件当前不可用")


def thread_detail(codex_home: Path, thread_id: str) -> dict:
    """Read one requested Codex index preview; never scan the rollout body."""
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    if not thread_id or len(thread_id) > 128 or any(char not in allowed for char in thread_id):
        raise HarborError("任务 ID 无效")
    database = state_database(codex_home)
    if not database:
        raise HarborError("Codex 任务索引当前不可用")
    try:
        with read_only_database(database) as connection:
            row = connection.execute(
                "SELECT id, title, preview, cwd, rollout_path, created_at, updated_at, created_at_ms, updated_at_ms, agent_nickname FROM threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise HarborError("无法读取 Codex 任务索引") from exc
    if not row:
        raise HarborError("Codex 索引中不存在该任务")
    rollout_path = indexed_rollout_path(codex_home, thread_id, row["rollout_path"])
    metadata = first_metadata(rollout_path)
    created = row["created_at_ms"] or ((row["created_at"] or 0) * 1000)
    updated = row["updated_at_ms"] or ((row["updated_at"] or 0) * 1000)
    indexed_title = compact_task_title(row["title"])
    if indexed_title.strip().lower() in {"hello", "hi", "你好"} and metadata.get("agent_path"):
        indexed_title = agent_task_title(metadata["agent_path"])
    preview = clean_index_text(row["preview"], 520)
    if metadata.get("parent_thread_id") and preview.strip().lower() in {"hello", "hi", "你好"}:
        preview = ""
    return {
        "id": str(row["id"]), "title": indexed_title or "未命名任务",
        "preview": preview, "cwd": str(row["cwd"] or ""),
        "rollout_path": str(rollout_path), "created_at_ms": int(created or 0),
        "updated_at_ms": int(updated or 0), "agent_nickname": str(row["agent_nickname"] or metadata.get("agent_nickname") or "").strip(),
        "parent_id": str(metadata.get("parent_thread_id") or ""),
        "agent_path": str(metadata.get("agent_path") or ""),
        "is_subagent": bool(metadata.get("parent_thread_id")),
    }


def task_record(codex_home: Path, thread_id: str, maximum_messages: int = 80) -> dict:
    """Read one requested sub-agent's visible status messages, excluding inherited parent history."""
    detail = thread_detail(codex_home, thread_id)
    if not detail["is_subagent"]:
        raise HarborError("该任务应直接在 Codex 中打开")
    path = Path(detail["rollout_path"])
    agent_path = detail["agent_path"]
    started = False
    messages: deque[dict] = deque(maxlen=maximum_messages)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = value.get("payload") or {}
                if not started and value.get("type") == "response_item" and payload.get("type") == "agent_message":
                    recipient = str(payload.get("recipient") or "")
                    content = payload.get("content") or []
                    marker = " ".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
                    if recipient == agent_path and "Message Type: NEW_TASK" in marker:
                        started = True
                    continue
                if not started or value.get("type") != "event_msg" or payload.get("type") != "agent_message":
                    continue
                message = str(payload.get("message") or "").strip()
                if message:
                    messages.append({"timestamp": value.get("timestamp"), "message": message[:12000]})
    except OSError as exc:
        raise HarborError("无法读取任务记录") from exc
    return {
        "id": thread_id,
        "title": detail["title"],
        "agent_nickname": detail["agent_nickname"],
        "parent_id": detail["parent_id"],
        "messages": list(messages),
        "truncated": len(messages) == maximum_messages,
    }


def attach_project(item: dict, catalog: dict) -> None:
    thread_ids = [value for value in (item.get("id"), item.get("parent_id")) if value]
    project_id = next((catalog["assignments"].get(value) for value in thread_ids if catalog["assignments"].get(value)), None)
    if not project_id and not any(value in catalog["projectless"] for value in thread_ids) and item.get("cwd"):
        try:
            cwd = Path(item["cwd"]).expanduser().resolve()
        except OSError:
            cwd = Path(item["cwd"]).expanduser().absolute()
        for candidate_id, project in catalog["projects"].items():
            for root_value in project["roots"]:
                try:
                    cwd.relative_to(Path(root_value).expanduser().resolve())
                    project_id = candidate_id
                    break
                except (ValueError, OSError):
                    continue
            if project_id:
                break
    project = catalog["projects"].get(project_id) if project_id else None
    item["project_id"] = project_id
    item["project_name"] = project["name"] if project else None
    item["project_path"] = project["roots"][0] if project and project["roots"] else None
    item["projectless"] = not bool(project_id)


def resolve_storage_target(data: dict) -> str:
    """Resolve the current storage contract without pretending cloud is shipped."""
    target = data.get("storage_target") or {}
    provider = target.get("provider") or "external_volume"
    location = target.get("location") or data.get("volume") or ""
    if provider != "external_volume":
        raise HarborError(f"该存储后端尚不可用：{provider}")
    return str(mounted_volume(location))


def session_record(path: Path, min_age: float, priority=None, protected_sessions=None) -> dict:
    linked = path.is_symlink()
    target = Path(os.readlink(path)) if linked else None
    target_exists = bool(target and target.is_file())
    backup = path.with_name(path.name + ".offload-local-backup")
    try:
        meta = first_metadata(path)
        error = None
    except Exception as exc:
        meta = {"id": None, "parent_thread_id": None, "cwd": None, "timestamp": None, "thread_source": None, "agent_nickname": None, "agent_path": None}
        _, error = user_error(exc)
    try:
        logical = path.stat().st_size
        modified = path.stat().st_mtime if not linked else (backup.stat().st_mtime if backup.is_file() else path.lstat().st_mtime)
        completed = last_turn_complete(path) if target_exists or not linked else False
    except OSError as exc:
        logical, modified, completed = 0, path.lstat().st_mtime, False
        _, message = user_error(exc)
        error = error or message
    age = max(0.0, (time.time() - modified) / 86400)
    kind = "child" if meta.get("parent_thread_id") else "main"
    reasons = []
    if error:
        reasons.append("unreadable")
    if kind != "child":
        reasons.append("main_task")
    if linked:
        reasons.append("already_offloaded" if target_exists else "drive_unavailable")
    if age < min_age:
        reasons.append("too_new")
    if not completed:
        reasons.append("last_turn_incomplete")
    project_protected = is_priority(meta.get("cwd"), priority)
    if project_protected:
        reasons.append("priority_project")
    session_protected = bool(meta.get("id") and meta.get("id") in set(protected_sessions or []))
    if session_protected:
        reasons.append("protected_session")
    return {
        "path": str(path), "name": path.name, "id": meta.get("id"), "parent_id": meta.get("parent_thread_id"),
        "thread_source": meta.get("thread_source"), "agent_nickname": meta.get("agent_nickname"), "agent_path": meta.get("agent_path"),
        "cwd": meta.get("cwd") or "", "timestamp": meta.get("timestamp"), "kind": kind, "logical": logical, "logical_h": human_bytes(logical),
        "local_allocated": local_allocated(path), "local_allocated_h": human_bytes(local_allocated(path)),
        "age_days": round(age, 1), "last_turn_complete": completed, "linked": linked,
        "target": str(target) if target else None, "target_exists": target_exists, "backup": str(backup),
        "backup_exists": backup.is_file(), "backup_bytes": backup.stat().st_size if backup.is_file() else 0,
        "eligible": not reasons, "reasons": reasons, "error": error, "protected_session": session_protected, "protected_project": project_protected,
    }


def scan(codex_home: Path, min_age: float = 30, priority=None, protected_sessions=None) -> dict:
    root = codex_home / "sessions"
    sessions = []
    volumes = available_volumes()
    imported_manifests = import_mounted_manifests(codex_home, volumes)
    catalog = load_project_catalog(codex_home)
    thread_catalog = load_thread_catalog(codex_home)
    if root.exists():
        for path in root.rglob("*.jsonl"):
            item = session_record(path, min_age, priority, protected_sessions)
            attach_project(item, catalog)
            attach_thread_title(item, thread_catalog)
            sessions.append(item)
    sessions.sort(key=lambda item: item["logical"], reverse=True)
    disk = shutil.disk_usage(Path.home())
    eligible = [item for item in sessions if item["eligible"]]
    rollback = sum(item["backup_bytes"] for item in sessions)
    totals = {
        "files": len(sessions), "main_files": sum(item["kind"] == "main" for item in sessions),
        "child_files": sum(item["kind"] == "child" for item in sessions), "linked_files": sum(item["linked"] for item in sessions),
        "logical": sum(item["logical"] for item in sessions), "local_allocated": sum(item["local_allocated"] for item in sessions) + rollback,
        "eligible": sum(item["logical"] for item in eligible), "eligible_files": len(eligible), "rollback": rollback,
    }
    for key in ("logical", "local_allocated", "eligible", "rollback"):
        totals[key + "_h"] = human_bytes(totals[key])
    catalog_result = catalog_update_from_scan(codex_home, sessions, volumes)
    catalog_result["manifests_imported"] = imported_manifests
    return {
        "version": VERSION, "codex_home": str(codex_home), "priority": priority or "", "min_age": min_age,
        "disk": {"free": disk.free, "free_h": human_bytes(disk.free), "total": disk.total, "used": disk.used,
                 "used_percent": round(disk.used / disk.total * 100, 1)},
        "totals": totals, "volumes": volumes, "storage_targets": available_storage_targets(volumes),
        "catalog": catalog_result, "sessions": sessions,
        "projects": list(catalog["projects"].values()), "generated_at": int(time.time()),
    }


def project_storage_plan(codex_home: Path, project_id: str) -> dict:
    """On-demand metadata-only inventory; normal scans never walk project assets."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", project_id):
        raise HarborError("项目标识无效")
    projects = load_project_catalog(codex_home)["projects"]
    project = projects.get(project_id)
    if not project or len(project["roots"]) != 1:
        raise HarborError("请选择一个具有单一本机目录的已保存项目")
    spec = importlib.util.spec_from_file_location("harbor_project_files", Path(__file__).with_name("project_files.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Saved rename aliases may point at the same local checkout. Keep the saved entry
    # while using its canonical local file paths; aliases into /Volumes are rejected.
    files = module.asset_plan(str(Path(project["roots"][0]).expanduser().resolve(strict=True)))
    config = load_config()
    if is_priority(project["roots"][0], config["protected_projects"]):
        files["retained"].append({"reason": "priority_project", "label": "项目已设为本机保留", "count": files["count"]})
        files["files"] = []; files["count"] = 0; files["total_bytes"] = 0
        for group in files["groups"]:
            group["candidate_count"] = 0; group["candidate_bytes"] = 0
    snapshot = scan(codex_home, 30, config["protected_projects"], config["protected_sessions"])
    histories = [item for item in snapshot["sessions"] if item.get("project_id") == project_id]
    reasons = {}
    for item in histories:
        if not item["linked"]:
            for reason in item["reasons"]:
                reasons[reason] = reasons.get(reason, 0) + 1
    return {"project": project, "files": files,
            "history": {"total": len(histories), "docked": sum(item["linked"] for item in histories),
                        "total_bytes": sum(item["logical"] for item in histories),
                        "docked_bytes": sum(item["logical"] for item in histories if item["linked"]),
                        "docked_online": sum(item["linked"] and item["target_exists"] for item in histories),
                        "eligible": sum(item["eligible"] for item in histories),
                        "eligible_bytes": sum(item["logical"] for item in histories if item["eligible"]),
                        "local_bytes": sum(item["logical"] for item in histories if not item["linked"]),
                        "retained": [{"reason": key, "label": REASON_LABELS.get(key, key), "count": value} for key, value in sorted(reasons.items())]},
            "continuity": {"original_root": project["roots"][0], "file_paths_preserved": True,
                           "offline_raw_read": False, "whole_active_workspace_external": False}}


def project_archive_module():
    spec = importlib.util.spec_from_file_location("harbor_archive_files", Path(__file__).with_name("archive_files.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offload_project_file(app: dict, data: dict, restore: bool = False) -> dict:
    """Execute only an exact source in the server-owned, volume-bound frozen plan."""
    frozen = app.get("project_plans", {}).get(str(data.get("plan_id") or ""))
    if not frozen or time.time() - frozen["created_at"] > 3600:
        raise HarborError("项目方案已过期，请重新查看后确认")
    if data.get("confirmation") != ("RESTORE PROJECT FILE" if restore else "DOCK PROJECT FILE"):
        raise HarborError("请先确认本次项目文件停泊方案")
    path = str(data.get("path") or "")
    row = frozen["rows"].get(path)
    if not row:
        raise HarborError("文件不在本次已确认项目方案中")
    config = load_config()
    if not restore and is_priority(frozen["root"], config["protected_projects"]):
        raise HarborError("项目已设为本机保留，停止停泊")
    volume = Path(frozen["volume"])
    if str(data.get("volume") or "") != str(volume):
        raise HarborError("目标盘已变化，请重新查看项目方案")
    def check_volume():
        verify_external_volume(volume, frozen["uuid"])
        return {"volume_uuid": frozen["uuid"], "volume_path": str(volume)}
    check_volume()
    module = project_archive_module()
    source = Path(row["source"])
    if source.parent.resolve() != source.parent:
        raise HarborError("项目父目录发生变化，停止停泊")
    if not restore:
        module.verify_planned_source(row)
    target = volume / DEFAULT_ARCHIVE / "Project Assets" / frozen["project_id"] / row["relative"]
    receipt = volume / DEFAULT_ARCHIVE / "Project Assets" / frozen["project_id"] / "archive-receipt.jsonl"
    module.safe_directory(receipt.parent)
    if restore:
        return module.restore_file(source, target, receipt, check_volume)
    return module.archive_file(source, target, receipt, check_volume,
                               keep_local=data.get("keep_local", True) is not False)


def parking_plan(app, data):
    """Freeze an exact mixed selection; adapters retain their own admission rules."""
    objects = data.get('objects') or []
    if not isinstance(objects, list) or not 0 < len(objects) <= 10000:
        raise HarborError('请选择 1 到 10000 个停泊对象')
    volume = mounted_volume(resolve_storage_target(data)); identity = volume_identity(volume)
    verify_external_volume(volume, identity.get('uuid', ''))
    cfg = load_config(); rows = []; seen = set(); archive = DEFAULT_ARCHIVE
    for obj in objects:
        if not isinstance(obj, dict):
            raise HarborError('停泊对象格式无效')
        path = str(obj.get('path') or '')
        if path in seen:
            raise HarborError('停泊对象重复')
        seen.add(path)
        kind = obj.get('kind')
        if kind == 'history':
            plan = plan_offload(path, app['codex_home'], str(volume), archive, 30,
                                cfg['protected_projects'], cfg['protected_sessions'])
            rows.append({'kind': kind, 'source': path, 'bytes': plan['bytes'], 'plan': plan})
        elif kind == 'file':
            frozen = app.get('project_plans', {}).get(str(obj.get('plan_id') or ''))
            if (not frozen or time.time()-frozen['created_at'] > 3600 or frozen['volume'] != str(volume)
                    or frozen['uuid'] != identity['uuid'] or path not in frozen['rows']):
                raise HarborError('项目文件不在当前有效的冻结方案中')
            row = frozen['rows'][path]
            if is_priority(frozen['root'], cfg['protected_projects']):
                raise HarborError('项目已设为本机保留，停止停泊')
            project_archive_module().verify_planned_source(row)
            rows.append({'kind': kind, 'source': path, 'bytes': row['bytes'],
                         'row': dict(row), 'root': frozen['root'], 'project_id': frozen['project_id']})
        else:
            raise HarborError('不支持的对象来源；不能绕过来源适配器')
    plans = app.setdefault('parking_plans', {})
    for key in list(plans):
        if time.time()-plans[key]['created_at'] > 3600:
            del plans[key]
    if len(plans) >= 10:
        raise HarborError('待确认方案过多，请重新打开港口')
    plan_id = secrets.token_urlsafe(24)
    plans[plan_id] = {'objects': rows, 'volume': str(volume), 'uuid': identity['uuid'], 'created_at': time.time()}
    return {'plan_id': plan_id, 'count': len(rows), 'bytes': sum(row['bytes'] for row in rows),
            'history_count': sum(row['kind'] == 'history' for row in rows),
            'file_count': sum(row['kind'] == 'file' for row in rows), 'volume_name': volume.name}


def start_parking(app, data):
    if data.get('confirmation') != 'DOCK SELECTED OBJECTS':
        raise HarborError('请先确认本次已选择的停泊对象')
    frozen = app.get('parking_plans', {}).get(str(data.get('plan_id') or ''))
    if not frozen or time.time()-frozen['created_at'] > 3600:
        raise HarborError('停泊方案已过期，请重新查看后确认')
    if data.get('volume') != frozen['volume']:
        raise HarborError('目标盘已变化，请重新确认')
    keep_local = data.get('keep_local', True) is not False
    if frozen.get('job_id'):
        if frozen['keep_local'] != keep_local:
            raise HarborError('已提交批次不能更改副本选择')
        return frozen['job_id']
    jobs = app.setdefault('parking_jobs', {})
    for key in list(jobs):
        if jobs[key]['status'] != 'running' and time.time()-jobs[key]['created_at'] > 3600:
            del jobs[key]
    if len(jobs) >= 20:
        raise HarborError('批次记录过多，请重新打开港口')
    job_id = secrets.token_urlsafe(24); frozen['job_id'] = job_id; frozen['keep_local'] = keep_local
    job = {'status': 'running', 'phase': 'waiting', 'completed': 0, 'total': len(frozen['objects']),
           'bytes': 0, 'total_bytes': sum(row['bytes'] for row in frozen['objects']), 'created_at': time.time()}
    jobs[job_id] = job
    def run():
        tick = time.perf_counter()
        try:
            with app['mutation_lock']:
                core = project_archive_module(); volume = Path(frozen['volume']); items = []
                def check_volume():
                    verify_external_volume(volume, frozen['uuid'])
                    return {'volume_uuid': frozen['uuid'], 'volume_path': str(volume)}
                check_volume()
                for descriptor in frozen['objects']:
                    if descriptor['kind'] == 'history':
                        item = history_parking_item(descriptor['plan'], volume, DEFAULT_ARCHIVE, app['codex_home'])
                        def validate(desc=descriptor):
                            cfg = load_config(); plan = desc['plan']
                            lexical_session(desc['source'], app['codex_home'])
                            if is_priority(plan.get('cwd', ''), cfg['protected_projects']) or plan.get('id') in cfg['protected_sessions']:
                                raise HarborError('历史已设为本机保留，停止停泊')
                        item['validate'] = validate
                    else:
                        row = descriptor['row']; root = volume / DEFAULT_ARCHIVE / 'Project Assets' / descriptor['project_id']
                        core.safe_directory(root)
                        def validate(desc=descriptor):
                            cfg = load_config()
                            if is_priority(desc['root'], cfg['protected_projects']):
                                raise HarborError('项目已设为本机保留，停止停泊')
                            if Path(desc['source']).parent.resolve() != Path(desc['source']).parent:
                                raise HarborError('项目父目录发生变化，停止停泊')
                            core.verify_planned_source(desc['row'])
                        item = {'source': descriptor['source'], 'target': str(root / row['relative']),
                                'receipt': str(root / 'archive-receipt.jsonl'), 'validate': validate}
                    items.append(item)
                prepared = time.perf_counter()-tick
                result = core.archive_batch(items, check_volume, keep_local=keep_local, progress=job.update)
                metrics = result['metrics']; metrics['adapter_seconds'] = prepared
                metrics['end_to_end_seconds'] = time.perf_counter()-tick
                job.update(status='complete', metrics=metrics, completed=len(result['results']),
                           bytes=metrics['verified_bytes'], released_bytes=metrics['released_bytes'])
                app['cache'] = None
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                exc = HarborError(str(exc))
            code, message = user_error(exc)
            if code == 'unexpected_error' and job['completed']:
                message = '停泊过程中发生异常；已完成对象保留，未完成对象已停止，请核对回执后恢复'
            job.update(status='failed', error_code=code, error=message,
                       elapsed_seconds=time.perf_counter()-tick)
            app['cache'] = None
    threading.Thread(target=run, daemon=True, name='harbor-parking').start()
    return job_id


def compact_summary(codex_home: Path, repair: bool = False) -> dict:
    """Return only the values needed by the native idle card."""
    if repair:
        volumes = available_volumes()
        import_mounted_manifests(codex_home, volumes)
        repair_links_by_volume_identity(codex_home, volumes)
    config = load_config()
    snapshot = scan(codex_home, 30, config["protected_projects"], config["protected_sessions"])
    volume = next((item for item in snapshot["volumes"] if item.get("writable")), None)
    docked = [item for item in snapshot["sessions"] if item.get("linked")]
    docked_available = sum(bool(item.get("target_exists")) for item in docked)
    return {
        "version": VERSION,
        "eligible_h": snapshot["totals"]["eligible_h"],
        "eligible_files": snapshot["totals"]["eligible_files"],
        "docked_files": len(docked),
        "docked_available": docked_available,
        "disk_free_h": snapshot["disk"]["free_h"],
        "volume_available": bool(volume),
        "volume_name": volume.get("name", "") if volume else "",
        "volume_free_h": volume.get("free_h", "") if volume else "",
    }


def append_manifest(volume: Path, archive_name: str, record: dict) -> str:
    manifest = volume / archive_name / "manifests" / "offload_manifest.jsonl"
    for ancestor in [manifest, *manifest.parents]:
        if ancestor.is_symlink():
            raise HarborError("校验清单路径包含链接，停止写入")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush(); os.fsync(stream.fileno())
    return str(manifest)


def file_signature(path: Path) -> tuple:
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def durable_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def verify_external_volume(volume: Path, expected_uuid: str) -> None:
    mounted_volume(str(volume))
    try:
        spec = importlib.util.spec_from_file_location('harbor_volume_probe', Path(__file__).with_name('volume_probe.py'))
        probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
        actual = probe.fresh_uuid(volume)
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        raise HarborError('无法重新确认外置卷身份，停止操作') from exc
    if not expected_uuid or actual.upper() != expected_uuid.upper():
        raise HarborError("外置卷身份与停泊方案不一致，停止操作")


def validate_archive_name(archive_name: str) -> None:
    if not archive_name or Path(archive_name).name != archive_name or archive_name in (".", ".."):
        raise HarborError("停泊目录名无效")


def recorded_copy(source: Path, target: Path) -> dict | None:
    """Find the expected digest in the append-only external receipt, not in the link."""
    for ancestor in target.parents:
        manifest = ancestor / "manifests/offload_manifest.jsonl"
        if not manifest.is_file():
            continue
        if manifest.is_symlink():
            raise HarborError("校验清单不是普通文件")
        record = None
        with manifest.open(encoding="utf-8") as stream:
            for line in stream:
                value = json.loads(line)
                if value.get("source") == str(source) and value.get("destination") == str(target):
                    record = value
        return record
    return None


def plan_offload(path_value: str, codex_home: Path, volume_value: str, archive_name: str, min_age: float, priority=None, protected_sessions=None) -> dict:
    validate_archive_name(archive_name)
    if min_age < 0:
        raise HarborError("静置天数不能为负数")
    source, relative = lexical_session(path_value, codex_home)
    volume = mounted_volume(volume_value)
    if source.is_symlink() or not source.is_file():
        raise HarborError("来源必须是本机的普通历史记录文件")
    item = session_record(source, min_age, priority, protected_sessions)
    attach_project(item, load_project_catalog(codex_home))
    attach_thread_title(item, load_thread_catalog(codex_home))
    if not item["eligible"]:
        reasons = [REASON_LABELS.get(reason, reason) for reason in item["reasons"]]
        raise HarborError("该历史记录当前不可停泊：" + "；".join(reasons))
    handles = open_handles(source)
    if handles:
        raise HarborError(f"该历史记录仍有 {handles} 个打开的文件句柄")
    destination = volume / archive_name / "sessions" / relative
    identity = volume_identity(volume)
    if not identity.get("uuid"):
        raise HarborError("无法确认外置卷持久身份，停止停泊")
    backup = source.with_name(source.name + ".offload-local-backup")
    if backup.exists() or backup.is_symlink():
        raise HarborError(f"本地回滚副本已存在：{backup}")
    return {
        "manifest_version": MANIFEST_SCHEMA_VERSION,
        "source": str(source), "destination": str(destination), "archive_relative": str(destination.relative_to(volume)),
        "backup": str(backup), "bytes": source.stat().st_size,
        "bytes_h": human_bytes(source.stat().st_size), "sha256": sha256(source),
        "id": item["id"], "parent_id": item.get("parent_id"), "kind": item.get("kind"),
        "title": item.get("title") or "", "cwd": item["cwd"], "agent_path": item.get("agent_path") or "",
        "timestamp": item.get("timestamp"), "project_id": item.get("project_id"),
        "project_name": item.get("project_name"), "project_path": item.get("project_path"),
        "volume_uuid": identity.get("uuid", ""), "volume_name": volume.name,
        "volume_path": str(volume), "source_signature": file_signature(source),
        "device_identifier": identity.get("device_identifier", ""), "open_handles": handles,
    }


def offload_one(plan: dict, volume: Path, archive_name: str, codex_home: Path | None = None) -> dict:
    return _offload_one(plan, volume, archive_name, codex_home)


def _offload_one(plan: dict, volume: Path, archive_name: str, codex_home: Path | None = None) -> dict:
    source, destination, backup = Path(plan["source"]), Path(plan["destination"]), Path(plan["backup"])
    validate_archive_name(archive_name)
    if codex_home:
        lexical_session(str(source), codex_home)
    if (not destination.is_relative_to(volume / archive_name / "sessions")
            or source.is_symlink() or not source.is_file()
            or backup.exists() or backup.is_symlink()):
        raise HarborError("来源、目标或回滚副本状态不符合停泊条件")
    item = history_parking_item(plan, volume, archive_name, codex_home)
    def handles(path):
        if open_handles(path):
            raise HarborError('记录仍在使用，停止停泊')
    def check_volume():
        verify_external_volume(volume, plan.get('volume_uuid', ''))
        return {'volume_uuid': plan.get('volume_uuid', ''), 'volume_path': str(volume)}
    try:
        result = project_archive_module().archive_batch([item], check_volume, handles, keep_local=True)['results'][0]
    except RuntimeError as exc:
        raise HarborError(str(exc)) from exc
    return {**result, 'event': 'offloaded_with_local_backup',
            'manifest': str(volume / archive_name / 'manifests/offload_manifest.jsonl')}


def history_parking_item(plan, volume, archive_name, codex_home=None):
    """Codex admission/receipt adapter; byte transactions live in the common core."""
    source, target = Path(plan['source']), Path(plan['destination'])
    if plan.get('source_signature') and not source.is_symlink() and tuple(plan['source_signature']) != file_signature(source):
        raise HarborError('来源与已确认方案不一致，停止停泊')
    recall = index_session_memory(str(source), codex_home, plan.get('sha256')) if codex_home and not source.is_symlink() else None
    extra = {**plan, 'event': 'offloaded_with_local_backup'}
    if recall:
        extra['recall_fragments'] = recall['fragments']
    def write(receipt, record):
        event = 'migrated_external_primary' if record['status'] == 'local_entity_released' else 'offloaded_with_local_backup'
        return append_manifest(volume, archive_name, {**record, 'event': event})
    return {'source': str(source), 'target': str(target),
            'receipt': str(volume / archive_name / 'manifests/offload_manifest.jsonl'),
            'backup_suffix': '.offload-local-backup', 'expected_hash': plan['sha256'],
            'source_signature': plan.get('source_signature'), 'record_extra': extra,
            'read_record': lambda receipt, source, target: recorded_copy(source, target), 'write_record': write}


def audit_one(path_value: str, codex_home: Path) -> dict:
    source, _ = lexical_session(path_value, codex_home)
    if not source.is_symlink():
        raise HarborError("来源不是停泊后的连续性链接")
    target = Path(os.readlink(source)); backup = source.with_name(source.name + ".offload-local-backup")
    result = {"source": str(source), "target": str(target), "target_exists": target.is_file(), "backup": str(backup), "backup_exists": backup.is_file()}
    if target.is_file(): result["target_sha256"] = sha256(target); result["source_sha256"] = sha256(source)
    if backup.is_file(): result["backup_sha256"] = sha256(backup)
    record = recorded_copy(source, target) if target.is_file() else None
    result["receipt_exists"] = bool(record)
    if record:
        result["expected_sha256"] = record.get("sha256")
        result["volume_uuid"] = record.get("volume_uuid", "")
        result["volume_path"] = record.get("volume_path") or (str(Path("/Volumes") / record["volume_name"]) if record.get("volume_name") else "")
    hashes = [value for key, value in result.items() if key.endswith("sha256")]
    result["verified"] = bool(record and target.stat().st_size == record.get("bytes")
                              and len(hashes) >= 3 and len(set(hashes)) == 1)
    return result


def finalize_one(path_value: str, codex_home: Path) -> dict:
    with project_archive_module().source_lock(Path(path_value)):
        return _finalize_one(path_value, codex_home)


def _finalize_one(path_value: str, codex_home: Path) -> dict:
    audit = audit_one(path_value, codex_home)
    if not audit["verified"] or not audit["backup_exists"]:
        raise HarborError("释放本地副本前必须同时具备已验证链接和本地回滚副本")
    if not audit.get("volume_path"):
        raise HarborError("校验记录缺少外置卷身份，保留本地副本")
    verify_external_volume(Path(audit["volume_path"]), audit.get("volume_uuid", ""))
    backup = Path(audit["backup"])
    if open_handles(backup) or open_handles(Path(audit["target"])):
        raise HarborError("记录仍在使用，保留本地副本")
    if sha256(backup) != audit["expected_sha256"] or sha256(Path(audit["target"])) != audit["expected_sha256"]:
        raise HarborError("释放前内容发生变化，保留本地副本")
    released = backup.stat().st_size; backup.unlink()
    durable_directory(backup.parent)
    return {**audit, "event": "local_backup_removed", "bytes_released": released, "bytes_released_h": human_bytes(released)}


def migrate_one(plan: dict, volume: Path, archive_name: str, codex_home: Path) -> dict:
    """Move one session to external primary storage and reclaim its local entity.

    The rollback copy is removed only after offload_one has verified the external
    copy and source link, and finalize_one has independently re-audited them.
    Any failure before that point leaves a recoverable local file in place.
    """
    moved = offload_one(plan, volume, archive_name, codex_home)
    finalized = finalize_one(plan["source"], codex_home)
    return {
        **moved,
        "event": "migrated_external_primary",
        "backup_exists": False,
        "bytes_released": finalized["bytes_released"],
        "bytes_released_h": finalized["bytes_released_h"],
    }


def migrate_path(path_value: str, codex_home: Path, volume: Path, archive_name: str, min_age: float, priority=None, protected_sessions=None) -> dict:
    """Idempotently complete one migration, including a previously interrupted one."""
    source, _ = lexical_session(path_value, codex_home)
    if source.is_symlink():
        audit = audit_one(path_value, codex_home)
        if not audit["verified"]:
            raise HarborError("现有停泊链接未通过校验")
        if not Path(audit["target"]).is_relative_to(volume / archive_name / "sessions"):
            raise HarborError("现有链接不属于本次选择的外置目标")
        if audit["backup_exists"]:
            finalized = finalize_one(path_value, codex_home)
            return {**audit, "event": "migrated_external_primary", "backup_exists": False, "bytes_released": finalized["bytes_released"], "bytes_released_h": finalized["bytes_released_h"]}
        return {**audit, "event": "already_migrated", "bytes_released": 0, "bytes_released_h": human_bytes(0)}
    plan = plan_offload(path_value, codex_home, str(volume), archive_name, min_age, priority, protected_sessions)
    return migrate_one(plan, volume, archive_name, codex_home)


def restore_one(path_value: str, codex_home: Path) -> dict:
    with project_archive_module().source_lock(Path(path_value)):
        return _restore_one(path_value, codex_home)


def _restore_one(path_value: str, codex_home: Path) -> dict:
    source, _ = lexical_session(path_value, codex_home)
    if not source.is_symlink(): raise HarborError("来源不是停泊后的连续性链接")
    target = Path(os.readlink(source))
    if not target.is_file(): raise HarborError("外部历史实体当前不可用")
    audit = audit_one(path_value, codex_home)
    if not audit["verified"]:
        raise HarborError("外部实体与原始校验记录不一致，停止恢复")
    if open_handles(source):
        raise HarborError("记录仍在使用，停止恢复")
    expected = audit["expected_sha256"]; backup = source.with_name(source.name + ".offload-local-backup")
    if backup.is_file():
        if sha256(backup) != expected: raise HarborError("本地回滚副本与外部历史实体不一致")
        if open_handles(backup):
            raise HarborError("本地副本仍在使用，停止恢复")
        os.replace(backup, source)
    else:
        temporary = source.with_name(source.name + ".restore-temp")
        with target.open("rb") as original, temporary.open("xb") as copied:
            shutil.copyfileobj(original, copied, 4 * 1024 * 1024)
            copied.flush(); os.fsync(copied.fileno())
        if sha256(temporary) != expected or sha256(target) != expected:
            raise HarborError("恢复后的副本校验失败；临时副本保留")
        os.replace(temporary, source)
    durable_directory(source.parent)
    return {"source": str(source), "target": str(target), "sha256": expected, "event": "restored_local_regular_file"}


class HarborHandler(BaseHTTPRequestHandler):
    server_version = "MemoryHarbor/" + VERSION
    def log_message(self, fmt, *args):
        sys.stderr.write("[harbor] " + fmt % args + "\n")
    @property
    def app(self): return self.server.app
    def send_json(self, status: int, value: dict):
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def body(self):
        length = int(self.headers.get("Content-Length", "0")); return json.loads(self.rfile.read(length) or b"{}")
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/parking-job':
            key = urllib.parse.parse_qs(parsed.query).get('id', [''])[0]
            job = self.app.get('parking_jobs', {}).get(key)
            return self.send_json(200 if job else 404, dict(job) if job else {'error': '批次记录不存在'})
        if parsed.path == "/api/scan":
            q = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            priority = (q["priority"][0] or None) if "priority" in q else (self.app["priority"] or None)
            age = float(q.get("min_age", ["30"])[0]); key = (age, priority or "")
            with self.app["cache_lock"]:
                cached = self.app.get("cache")
                if cached and cached["key"] == key and time.time() - cached["at"] < 8:
                    result = cached["value"]
                else:
                    result = scan(self.app["codex_home"], age, priority, self.app["protected_sessions"])
                    self.app["cache"] = {"key": key, "at": time.time(), "value": result}
            return self.send_json(200, result)
        if parsed.path == "/api/volumes":
            return self.send_json(200, {"volumes": available_volumes(), "generated_at": int(time.time())})
        if parsed.path == "/api/storage-targets":
            return self.send_json(200, {"storage_targets": available_storage_targets(), "generated_at": int(time.time())})
        if parsed.path == "/api/catalog":
            return self.send_json(200, {"catalog": catalog_status(self.app["codex_home"])})
        if parsed.path == "/api/search":
            q = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            query = q.get("q", [""])[0]
            limit = int(q.get("limit", ["30"])[0])
            return self.send_json(200, {"query": query, "results": catalog_search(self.app["codex_home"], query, limit)})
        if parsed.path == "/api/recall":
            q = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            query = q.get("q", [""])[0]
            limit = int(q.get("limit", ["30"])[0])
            return self.send_json(200, {"query": query, "results": recall_search(self.app["codex_home"], query, limit)})
        if parsed.path == "/api/config": return self.send_json(200, {"token": self.app["token"], "version": VERSION, "priority": self.app["priority"], "protected_projects": parse_projects(self.app["priority"]), "protected_sessions": self.app["protected_sessions"]})
        asset = "index.html" if parsed.path in ("/", "") else parsed.path.lstrip("/")
        file = (self.app["assets"] / asset).resolve()
        if not str(file).startswith(str(self.app["assets"].resolve())) or not file.is_file(): return self.send_error(404)
        raw = file.read_bytes(); self.send_response(200); self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        if self.headers.get("X-Harbor-Token") != self.app["token"]: return self.send_json(403, {"error_code": "invalid_action_token", "error": "操作令牌无效，请重新打开仪表盘"})
        mutation_lock = self.app.get("mutation_lock") if self.path in ("/api/offload", "/api/migrate", "/api/finalize", "/api/restore", "/api/project-file-offload", "/api/project-file-restore", "/api/repair-links", "/api/protect", "/api/settings", '/api/parking-plan', '/api/parking-start') else None
        if mutation_lock:
            mutation_lock.acquire()
        try:
            data = self.body()
            if self.path == '/api/parking-plan':
                return self.send_json(200, {'ok': True, 'plan': parking_plan(self.app, data)})
            if self.path == '/api/parking-start':
                return self.send_json(200, {'ok': True, 'job_id': start_parking(self.app, data)})
            if self.path == "/api/settings":
                saved = save_config(data.get("protected_projects", data.get("priority", [])), data.get("protected_sessions", self.app["protected_sessions"])); self.app["priority"] = "\n".join(saved["protected_projects"]); self.app["protected_sessions"] = saved["protected_sessions"]
                self.app["cache"] = None
                return self.send_json(200, {"ok": True, "settings": saved})
            if self.path == "/api/protect":
                cfg = load_config(); scope, value, enabled = data.get("scope"), str(data.get("value") or ""), bool(data.get("enabled"))
                if scope not in ("project", "session") or not value: raise HarborError("保护目标无效")
                key = "protected_projects" if scope == "project" else "protected_sessions"; values = set(cfg[key])
                values.add(value) if enabled else values.discard(value); cfg[key] = sorted(values)
                saved = save_config(cfg["protected_projects"], cfg["protected_sessions"]); self.app["priority"] = "\n".join(saved["protected_projects"]); self.app["protected_sessions"] = saved["protected_sessions"]; self.app["cache"] = None
                return self.send_json(200, {"ok": True, "settings": saved})
            if self.path == "/api/task-detail":
                return self.send_json(200, {"ok": True, "task": thread_detail(self.app["codex_home"], str(data.get("id") or ""))})
            if self.path == "/api/project-plan":
                result = project_storage_plan(self.app["codex_home"], str(data.get("project_id") or ""))
                volume = mounted_volume(resolve_storage_target(data))
                uuid = volume_identity(volume).get("uuid", "")
                verify_external_volume(volume, uuid)
                plan_id = secrets.token_urlsafe(24)
                plans = self.app.setdefault("project_plans", {})
                for key in list(plans):
                    if time.time() - plans[key]["created_at"] > 3600: del plans[key]
                if len(plans) >= 10:
                    raise HarborError("待确认方案过多，请关闭并重新打开港口")
                plans[plan_id] = {"rows": {row["source"]: row for row in result["files"]["files"]},
                                  "project_id": result["project"]["id"], "root": result["files"]["project_root"],
                                  "volume": str(volume), "uuid": uuid, "created_at": time.time()}
                for row in result["files"]["parked_files"]:
                    expected = volume / DEFAULT_ARCHIVE / "Project Assets" / result["project"]["id"] / row["relative"]
                    if row["target"] == str(expected):
                        plans[plan_id]["rows"][row["source"]] = row
                        row["restorable"] = True
                result["plan_id"] = plan_id
                result["volume"] = {"path": str(volume), "uuid": uuid, "name": volume.name}
                return self.send_json(200, {"ok": True, "plan": result})
            if self.path == "/api/project-file-offload":
                result = offload_project_file(self.app, data)
                self.app["cache"] = None
                return self.send_json(200, {"ok": True, "result": result})
            if self.path == "/api/project-file-restore":
                result = offload_project_file(self.app, data, restore=True)
                self.app["cache"] = None
                return self.send_json(200, {"ok": True, "result": result})
            if self.path == "/api/task-record":
                return self.send_json(200, {"ok": True, "record": task_record(self.app["codex_home"], str(data.get("id") or ""))})
            if self.path == "/api/rebuild-catalog":
                result = rebuild_catalog(self.app["codex_home"], 30, self.app["priority"] or None, self.app["protected_sessions"])
                self.app["cache"] = None
                return self.send_json(200, {"ok": True, **result})
            if self.path == "/api/repair-links":
                repaired = repair_links_by_volume_identity(self.app["codex_home"], available_volumes())
                self.app["cache"] = None
                return self.send_json(200, {"ok": True, "repaired": repaired})
            if self.path == "/api/build-recall-index":
                result = build_recall_index(
                    self.app["codex_home"], data.get("paths") or None, bool(data.get("linked_only", True))
                )
                return self.send_json(200, {"ok": not bool(result["errors"]), **result})
            paths = data.get("paths") or []
            if not paths: raise HarborError("尚未选择任何历史记录")
            results = []
            if self.path == "/api/plan":
                volume_value = resolve_storage_target(data)
                for path in paths: results.append(plan_offload(path, self.app["codex_home"], volume_value, data.get("archive_name") or DEFAULT_ARCHIVE, float(data.get("min_age", 30)), self.app["priority"] or None, self.app["protected_sessions"]))
            elif self.path in ("/api/offload", "/api/migrate"):
                volume = mounted_volume(resolve_storage_target(data)); archive = data.get("archive_name") or DEFAULT_ARCHIVE
                for path in paths:
                    if self.path == "/api/migrate":
                        results.append(migrate_path(path, self.app["codex_home"], volume, archive, float(data.get("min_age", 30)), self.app["priority"] or None, self.app["protected_sessions"]))
                    else:
                        plan = plan_offload(path, self.app["codex_home"], str(volume), archive, float(data.get("min_age", 30)), self.app["priority"] or None, self.app["protected_sessions"])
                        results.append(offload_one(plan, volume, archive, self.app["codex_home"]))
            elif self.path == "/api/audit":
                for path in paths: results.append(audit_one(path, self.app["codex_home"]))
            elif self.path == "/api/finalize":
                if data.get("confirmation") != "DELETE LOCAL BACKUPS": raise HarborError("确认短语不匹配")
                for path in paths: results.append(finalize_one(path, self.app["codex_home"]))
            elif self.path == "/api/restore":
                for path in paths: results.append(restore_one(path, self.app["codex_home"]))
            else: return self.send_error(404)
            self.app["cache"] = None
            self.send_json(200, {"ok": True, "results": results})
        except Exception as exc:
            sys.stderr.write(f"[harbor] {type(exc).__name__}: {exc}\n")
            code, message = user_error(exc)
            self.send_json(400, {"ok": False, "error_code": code, "error": message})
        finally:
            if mutation_lock:
                mutation_lock.release()


def stop_server_when_parent_exits(server: ThreadingHTTPServer, parent_pid: int) -> None:
    """Stop a helper-owned server even if its macOS parent is killed abruptly."""
    if parent_pid <= 1:
        return
    if hasattr(select, "kqueue"):
        queue = select.kqueue()
        try:
            event = select.kevent(
                parent_pid,
                filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
                fflags=select.KQ_NOTE_EXIT,
            )
            queue.control([event], 0, 0)
            queue.control(None, 1, None)
        except OSError:
            pass
        finally:
            queue.close()
    else:
        while os.getppid() == parent_pid:
            time.sleep(0.25)
    server.shutdown()


def serve(args) -> None:
    assets = Path(__file__).resolve().parent.parent / "assets" / "dashboard"
    token = secrets.token_urlsafe(24); codex_home = Path(args.codex_home or os.environ.get("CODEX_HOME", "~/.codex")).expanduser().absolute()
    config = load_config(); priority = "\n".join(config["protected_projects"])
    server = ThreadingHTTPServer(("127.0.0.1", args.port), HarborHandler); server.app = {"assets": assets, "token": token, "codex_home": codex_home, "priority": priority, "protected_sessions": config["protected_sessions"], "cache": None, "cache_lock": threading.Lock(), "mutation_lock": threading.Lock()}
    if args.parent_pid:
        threading.Thread(target=stop_server_when_parent_exits, args=(server, args.parent_pid), daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    print(json.dumps({"url": url, "version": VERSION, "codex_home": str(codex_home)}, ensure_ascii=False), flush=True)
    if args.open: threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--codex-home")
    sub = parser.add_subparsers(dest="command", required=True)
    scan_p = sub.add_parser("scan"); scan_p.add_argument("--min-age", type=float, default=30); scan_p.add_argument("--priority")
    serve_p = sub.add_parser("serve"); serve_p.add_argument("--port", type=int, default=48765); serve_p.add_argument("--parent-pid", type=int); serve_p.add_argument("--open", action="store_true")
    audit_p = sub.add_parser("audit"); audit_p.add_argument("path")
    search_p = sub.add_parser("search"); search_p.add_argument("query"); search_p.add_argument("--limit", type=int, default=20)
    recall_p = sub.add_parser("recall"); recall_p.add_argument("query"); recall_p.add_argument("--limit", type=int, default=20)
    recall_index_p = sub.add_parser("build-recall-index"); recall_index_p.add_argument("paths", nargs="*"); recall_index_p.add_argument("--all-child", action="store_true")
    recall_clear_p = sub.add_parser("clear-recall-index"); recall_clear_p.add_argument("paths", nargs="*")
    sub.add_parser("rebuild-index")
    sub.add_parser("index-status")
    sub.add_parser("repair-links")
    project_p = sub.add_parser("project-plan", help="按已保存项目盘点素材与历史；不移动文件")
    project_p.add_argument("project_id")
    compact_p = sub.add_parser("compact-status"); compact_p.add_argument("--repair-links", action="store_true")
    args = parser.parse_args()
    home = Path(args.codex_home or os.environ.get("CODEX_HOME", "~/.codex")).expanduser().absolute()
    try:
        if args.command == "scan":
            config = load_config(); projects = args.priority if args.priority is not None else config["protected_projects"]
            print(json.dumps(scan(home, args.min_age, projects, config["protected_sessions"]), ensure_ascii=False, indent=2))
        elif args.command == "serve": serve(args)
        elif args.command == "audit": print(json.dumps(audit_one(args.path, home), ensure_ascii=False, indent=2))
        elif args.command == "search":
            if not catalog_path(home).is_file():
                config = load_config(); scan(home, 30, config["protected_projects"], config["protected_sessions"])
            print(json.dumps({"query": args.query, "results": catalog_search(home, args.query, args.limit)}, ensure_ascii=False, indent=2))
        elif args.command == "recall":
            if not catalog_path(home).is_file():
                config = load_config(); scan(home, 30, config["protected_projects"], config["protected_sessions"])
            print(json.dumps({"query": args.query, "results": recall_search(home, args.query, args.limit)}, ensure_ascii=False, indent=2))
        elif args.command == "build-recall-index":
            print(json.dumps(build_recall_index(home, args.paths or None, not args.all_child), ensure_ascii=False, indent=2))
        elif args.command == "clear-recall-index":
            print(json.dumps(clear_recall_index(home, args.paths or None), ensure_ascii=False, indent=2))
        elif args.command == "rebuild-index":
            config = load_config(); print(json.dumps(rebuild_catalog(home, 30, config["protected_projects"], config["protected_sessions"]), ensure_ascii=False, indent=2))
        elif args.command == "index-status": print(json.dumps(catalog_status(home), ensure_ascii=False, indent=2))
        elif args.command == "project-plan":
            print(json.dumps(project_storage_plan(home, args.project_id), ensure_ascii=False, indent=2))
        elif args.command == "repair-links":
            volumes = available_volumes(); import_mounted_manifests(home, volumes)
            print(json.dumps({"repaired": repair_links_by_volume_identity(home, volumes)}, ensure_ascii=False, indent=2))
        elif args.command == "compact-status":
            print(json.dumps(compact_summary(home, args.repair_links), ensure_ascii=False))
    except (HarborError, OSError, ValueError, json.JSONDecodeError) as exc:
        code, message = user_error(exc)
        print(f"错误 [{code}]：{message}", file=sys.stderr); return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
