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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.2.3-beta.1"
DEFAULT_ARCHIVE = "Codex Memory Harbor"


class HarborError(RuntimeError):
    pass


def config_path() -> Path:
    return Path(os.environ.get("CODEX_HARBOR_CONFIG", "~/.config/codex-memory-harbor/config.json")).expanduser()


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
        result.append({"path": str(volume), "name": volume.name, "free": usage.free, "free_h": human_bytes(usage.free), "writable": writable})
    return result


def available_storage_targets() -> list[dict]:
    """Stable provider boundary: cloud backends can implement this contract later."""
    targets = [
        {
            "id": f"external:{volume['path']}",
            "provider": "external_volume",
            "location": volume["path"],
            "name": volume["name"],
            "available": volume["writable"],
            "free": volume["free"],
            "free_h": volume["free_h"],
        }
        for volume in available_volumes()
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
    return {
        "version": VERSION, "codex_home": str(codex_home), "priority": priority or "", "min_age": min_age,
        "disk": {"free": disk.free, "free_h": human_bytes(disk.free), "total": disk.total, "used": disk.used,
                 "used_percent": round(disk.used / disk.total * 100, 1)},
        "totals": totals, "volumes": available_volumes(), "storage_targets": available_storage_targets(), "sessions": sessions, "generated_at": int(time.time()),
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
    if not item["eligible"]:
        raise HarborError("Session is not eligible: " + ", ".join(item["reasons"]))
    handles = open_handles(source)
    if handles:
        raise HarborError(f"Session has {handles} open handles")
    destination = volume / archive_name / "sessions" / relative
    backup = source.with_name(source.name + ".offload-local-backup")
    if backup.exists() or backup.is_symlink():
        raise HarborError(f"Rollback copy already exists: {backup}")
    return {"source": str(source), "destination": str(destination), "backup": str(backup), "bytes": source.stat().st_size,
            "bytes_h": human_bytes(source.stat().st_size), "sha256": sha256(source), "id": item["id"], "cwd": item["cwd"], "open_handles": handles}


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
    args = parser.parse_args()
    home = Path(args.codex_home or os.environ.get("CODEX_HOME", "~/.codex")).expanduser().absolute()
    try:
        if args.command == "scan":
            config = load_config(); projects = args.priority if args.priority is not None else config["protected_projects"]
            print(json.dumps(scan(home, args.min_age, projects, config["protected_sessions"]), ensure_ascii=False, indent=2))
        elif args.command == "serve": serve(args)
        elif args.command == "audit": print(json.dumps(audit_one(args.path, home), ensure_ascii=False, indent=2))
    except (HarborError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
