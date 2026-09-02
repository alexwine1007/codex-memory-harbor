#!/usr/bin/env python3
"""Codex Memory Harbor: local inventory, verified offload, recovery, and dashboard."""

from __future__ import annotations

import argparse
import hashlib
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
from collections import deque
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.3.0-beta.1"
DEFAULT_ARCHIVE = "Codex Memory Harbor"
CATALOG_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 2


class HarborError(RuntimeError):
    pass


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
    except (OSError, ValueError, json.JSONDecodeError):
        return {"protected_projects": [], "protected_sessions": []}


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
    result = subprocess.run(["lsof", str(path)], capture_output=True, text=True, check=False)
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
    path = Path(path_value).expanduser().absolute()
    root = (codex_home / "sessions").absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise HarborError(f"Session must be under {root}") from exc
    return path, relative


def mounted_volume(path_value: str) -> Path:
    volume = Path(path_value).expanduser().absolute()
    if not str(volume).startswith("/Volumes/"):
        raise HarborError("External volume must be mounted under /Volumes")
    if not volume.is_dir() or not os.path.ismount(volume):
        raise HarborError(f"External volume is not mounted: {volume}")
    if not os.access(volume, os.W_OK):
        raise HarborError(f"External volume is not writable: {volume}")
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
    return connection


@contextmanager
def managed_catalog(codex_home: Path):
    connection = open_catalog(codex_home)
    try:
        with connection:
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
    return {"path": str(catalog_path(codex_home)), "items": count, "updated_at": now}


def catalog_search(codex_home: Path, query: str, limit: int = 20) -> list[dict]:
    query = clean_index_text(query, 300)
    if not query:
        return []
    limit = max(1, min(int(limit), 100))
    with managed_catalog(codex_home) as connection:
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
    return {
        "path": str(catalog_path(codex_home)), "schema_version": CATALOG_SCHEMA_VERSION,
        "items": int(row["items"] or 0), "present": int(row["present"] or 0),
        "linked": int(row["linked"] or 0), "targets_available": int(row["targets_available"] or 0),
        "updated_at": int(row["updated_at"] or 0), "fts_tokenizer": tokenizer[0] if tokenizer else "unknown",
    }


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
        for volume in volumes:
            manifest = Path(volume["path"]) / archive_name / "manifests" / "offload_manifest.jsonl"
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
                relative = manifest_relative(raw, archive_name)
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
    raise HarborError("Task record file is unavailable")


def thread_detail(codex_home: Path, thread_id: str) -> dict:
    """Read one requested Codex index preview; never scan the rollout body."""
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    if not thread_id or len(thread_id) > 128 or any(char not in allowed for char in thread_id):
        raise HarborError("Invalid task id")
    database = state_database(codex_home)
    if not database:
        raise HarborError("Codex task index is unavailable")
    try:
        with read_only_database(database) as connection:
            row = connection.execute(
                "SELECT id, title, preview, cwd, rollout_path, created_at, updated_at, created_at_ms, updated_at_ms, agent_nickname FROM threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise HarborError("Unable to read the Codex task index") from exc
    if not row:
        raise HarborError("Task is not present in the Codex index")
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
        raise HarborError("This task opens directly in Codex")
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
        raise HarborError("Unable to read the task record") from exc
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
        raise HarborError(f"Storage provider is not available yet: {provider}")
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
        error = str(exc)
    try:
        logical = path.stat().st_size
        modified = path.stat().st_mtime if not linked else (backup.stat().st_mtime if backup.is_file() else path.lstat().st_mtime)
        completed = last_turn_complete(path) if target_exists or not linked else False
    except OSError as exc:
        logical, modified, completed = 0, path.lstat().st_mtime, False
        error = error or str(exc)
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
        "catalog": catalog_result, "sessions": sessions, "generated_at": int(time.time()),
    }


def append_manifest(volume: Path, archive_name: str, record: dict) -> str:
    manifest = volume / archive_name / "manifests" / "offload_manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush(); os.fsync(stream.fileno())
    return str(manifest)


def plan_offload(path_value: str, codex_home: Path, volume_value: str, archive_name: str, min_age: float, priority=None, protected_sessions=None) -> dict:
    source, relative = lexical_session(path_value, codex_home)
    volume = mounted_volume(volume_value)
    if source.is_symlink() or not source.is_file():
        raise HarborError("Source must be a local regular session file")
    item = session_record(source, min_age, priority, protected_sessions)
    attach_project(item, load_project_catalog(codex_home))
    attach_thread_title(item, load_thread_catalog(codex_home))
    if not item["eligible"]:
        raise HarborError("Session is not eligible: " + ", ".join(item["reasons"]))
    handles = open_handles(source)
    if handles:
        raise HarborError(f"Session has {handles} open handles")
    destination = volume / archive_name / "sessions" / relative
    identity = volume_identity(volume)
    backup = source.with_name(source.name + ".offload-local-backup")
    if backup.exists() or backup.is_symlink():
        raise HarborError(f"Rollback copy already exists: {backup}")
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
        "device_identifier": identity.get("device_identifier", ""), "open_handles": handles,
    }


def offload_one(plan: dict, volume: Path, archive_name: str) -> dict:
    source, destination, backup = Path(plan["source"]), Path(plan["destination"]), Path(plan["backup"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if destination.stat().st_size != plan["bytes"] or sha256(destination) != plan["sha256"]:
        destination.unlink(missing_ok=True)
        raise HarborError("External copy verification failed")
    os.replace(source, backup)
    try:
        source.symlink_to(destination)
        if sha256(source) != plan["sha256"]:
            raise HarborError("Symlink verification failed")
    except Exception:
        source.unlink(missing_ok=True); os.replace(backup, source); raise
    record = {**plan, "event": "offloaded_with_local_backup", "recorded_at": int(time.time())}
    record["manifest"] = append_manifest(volume, archive_name, record)
    return record


def audit_one(path_value: str, codex_home: Path) -> dict:
    source, _ = lexical_session(path_value, codex_home)
    if not source.is_symlink():
        raise HarborError("Source is not an offload symlink")
    target = Path(os.readlink(source)); backup = source.with_name(source.name + ".offload-local-backup")
    result = {"source": str(source), "target": str(target), "target_exists": target.is_file(), "backup": str(backup), "backup_exists": backup.is_file()}
    if target.is_file(): result["target_sha256"] = sha256(target); result["source_sha256"] = sha256(source)
    if backup.is_file(): result["backup_sha256"] = sha256(backup)
    hashes = [value for key, value in result.items() if key.endswith("sha256")]
    result["verified"] = len(hashes) >= 2 and len(set(hashes)) == 1
    return result


def finalize_one(path_value: str, codex_home: Path) -> dict:
    audit = audit_one(path_value, codex_home)
    if not audit["verified"] or not audit["backup_exists"]:
        raise HarborError("A verified link and local rollback copy are required")
    backup = Path(audit["backup"]); released = backup.stat().st_size; backup.unlink()
    return {**audit, "event": "local_backup_removed", "bytes_released": released, "bytes_released_h": human_bytes(released)}


def restore_one(path_value: str, codex_home: Path) -> dict:
    source, _ = lexical_session(path_value, codex_home)
    if not source.is_symlink(): raise HarborError("Source is not an offload symlink")
    target = Path(os.readlink(source))
    if not target.is_file(): raise HarborError("External target is unavailable")
    expected = sha256(target); backup = source.with_name(source.name + ".offload-local-backup")
    if backup.is_file():
        if sha256(backup) != expected: raise HarborError("Rollback copy does not match external target")
        source.unlink(); os.replace(backup, source)
    else:
        temporary = source.with_name(source.name + ".restore-temp")
        shutil.copy2(target, temporary)
        if sha256(temporary) != expected: temporary.unlink(missing_ok=True); raise HarborError("Restored copy verification failed")
        source.unlink(); os.replace(temporary, source)
    return {"source": str(source), "target": str(target), "sha256": expected, "event": "restored_local_regular_file"}


class HarborHandler(BaseHTTPRequestHandler):
    server_version = "CodexMemoryHarbor/" + VERSION
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
        if parsed.path == "/api/config": return self.send_json(200, {"token": self.app["token"], "version": VERSION, "priority": self.app["priority"], "protected_projects": parse_projects(self.app["priority"]), "protected_sessions": self.app["protected_sessions"]})
        asset = "index.html" if parsed.path in ("/", "") else parsed.path.lstrip("/")
        file = (self.app["assets"] / asset).resolve()
        if not str(file).startswith(str(self.app["assets"].resolve())) or not file.is_file(): return self.send_error(404)
        raw = file.read_bytes(); self.send_response(200); self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        if self.headers.get("X-Harbor-Token") != self.app["token"]: return self.send_json(403, {"error": "Invalid action token"})
        try:
            data = self.body()
            if self.path == "/api/settings":
                saved = save_config(data.get("protected_projects", data.get("priority", [])), data.get("protected_sessions", self.app["protected_sessions"])); self.app["priority"] = "\n".join(saved["protected_projects"]); self.app["protected_sessions"] = saved["protected_sessions"]
                self.app["cache"] = None
                return self.send_json(200, {"ok": True, "settings": saved})
            if self.path == "/api/protect":
                cfg = load_config(); scope, value, enabled = data.get("scope"), str(data.get("value") or ""), bool(data.get("enabled"))
                if scope not in ("project", "session") or not value: raise HarborError("Invalid protection target")
                key = "protected_projects" if scope == "project" else "protected_sessions"; values = set(cfg[key])
                values.add(value) if enabled else values.discard(value); cfg[key] = sorted(values)
                saved = save_config(cfg["protected_projects"], cfg["protected_sessions"]); self.app["priority"] = "\n".join(saved["protected_projects"]); self.app["protected_sessions"] = saved["protected_sessions"]; self.app["cache"] = None
                return self.send_json(200, {"ok": True, "settings": saved})
            if self.path == "/api/task-detail":
                return self.send_json(200, {"ok": True, "task": thread_detail(self.app["codex_home"], str(data.get("id") or ""))})
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
            paths = data.get("paths") or []
            if not paths: raise HarborError("No sessions selected")
            results = []
            if self.path == "/api/plan":
                volume_value = resolve_storage_target(data)
                for path in paths: results.append(plan_offload(path, self.app["codex_home"], volume_value, data.get("archive_name") or DEFAULT_ARCHIVE, float(data.get("min_age", 30)), data.get("priority") or None, self.app["protected_sessions"]))
            elif self.path == "/api/offload":
                volume = mounted_volume(resolve_storage_target(data)); archive = data.get("archive_name") or DEFAULT_ARCHIVE
                for path in paths:
                    plan = plan_offload(path, self.app["codex_home"], str(volume), archive, float(data.get("min_age", 30)), data.get("priority") or None, self.app["protected_sessions"])
                    results.append(offload_one(plan, volume, archive))
            elif self.path == "/api/audit":
                for path in paths: results.append(audit_one(path, self.app["codex_home"]))
            elif self.path == "/api/finalize":
                if data.get("confirmation") != "DELETE LOCAL BACKUPS": raise HarborError("Confirmation phrase does not match")
                for path in paths: results.append(finalize_one(path, self.app["codex_home"]))
            elif self.path == "/api/restore":
                for path in paths: results.append(restore_one(path, self.app["codex_home"]))
            else: return self.send_error(404)
            self.app["cache"] = None
            self.send_json(200, {"ok": True, "results": results})
        except Exception as exc:
            self.send_json(400, {"ok": False, "error": str(exc)})


def serve(args) -> None:
    assets = Path(__file__).resolve().parent.parent / "assets" / "dashboard"
    token = secrets.token_urlsafe(24); codex_home = Path(args.codex_home or os.environ.get("CODEX_HOME", "~/.codex")).expanduser().absolute()
    config = load_config(); priority = "\n".join(config["protected_projects"])
    server = ThreadingHTTPServer(("127.0.0.1", args.port), HarborHandler); server.app = {"assets": assets, "token": token, "codex_home": codex_home, "priority": priority, "protected_sessions": config["protected_sessions"], "cache": None, "cache_lock": threading.Lock()}
    url = f"http://127.0.0.1:{server.server_port}/"
    print(json.dumps({"url": url, "version": VERSION, "codex_home": str(codex_home)}, ensure_ascii=False), flush=True)
    if args.open: threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--codex-home")
    sub = parser.add_subparsers(dest="command", required=True)
    scan_p = sub.add_parser("scan"); scan_p.add_argument("--min-age", type=float, default=30); scan_p.add_argument("--priority")
    serve_p = sub.add_parser("serve"); serve_p.add_argument("--port", type=int, default=48765); serve_p.add_argument("--open", action="store_true")
    audit_p = sub.add_parser("audit"); audit_p.add_argument("path")
    search_p = sub.add_parser("search"); search_p.add_argument("query"); search_p.add_argument("--limit", type=int, default=20)
    sub.add_parser("rebuild-index")
    sub.add_parser("index-status")
    sub.add_parser("repair-links")
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
        elif args.command == "rebuild-index":
            config = load_config(); print(json.dumps(rebuild_catalog(home, 30, config["protected_projects"], config["protected_sessions"]), ensure_ascii=False, indent=2))
        elif args.command == "index-status": print(json.dumps(catalog_status(home), ensure_ascii=False, indent=2))
        elif args.command == "repair-links":
            volumes = available_volumes(); import_mounted_manifests(home, volumes)
            print(json.dumps({"repaired": repair_links_by_volume_identity(home, volumes)}, ensure_ascii=False, indent=2))
    except (HarborError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
