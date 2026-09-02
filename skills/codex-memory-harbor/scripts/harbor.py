#!/usr/bin/env python3
"""Codex Memory Harbor: local inventory, verified offload, recovery, and dashboard."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.1.0-beta.1"
DEFAULT_ARCHIVE = "Codex Memory Harbor"


class HarborError(RuntimeError):
    pass


def config_path() -> Path:
    return Path(os.environ.get("CODEX_HARBOR_CONFIG", "~/.config/codex-memory-harbor/config.json")).expanduser()


def load_config() -> dict:
    path = config_path()
    if not path.is_file():
        return {"priority": ""}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return {"priority": str(value.get("priority") or "")}
    except (OSError, ValueError, json.JSONDecodeError):
        return {"priority": ""}


def save_config(priority: str) -> dict:
    path = config_path(); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    value = {"priority": priority.strip(), "updated_at": int(time.time())}
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
    return {
        "id": payload.get("id"),
        "parent_thread_id": payload.get("parent_thread_id"),
        "cwd": payload.get("cwd"),
        "timestamp": payload.get("timestamp"),
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


def is_priority(cwd: str | None, priority: str | None) -> bool:
    if not cwd or not priority:
        return False
    try:
        Path(cwd).expanduser().resolve().relative_to(Path(priority).expanduser().resolve())
        return True
    except (ValueError, OSError):
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


def session_record(path: Path, min_age: float, priority: str | None) -> dict:
    linked = path.is_symlink()
    target = Path(os.readlink(path)) if linked else None
    target_exists = bool(target and target.is_file())
    backup = path.with_name(path.name + ".offload-local-backup")
    try:
        meta = first_metadata(path)
        error = None
    except Exception as exc:
        meta = {"id": None, "parent_thread_id": None, "cwd": None, "timestamp": None}
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
    if is_priority(meta.get("cwd"), priority):
        reasons.append("priority_project")
    return {
        "path": str(path), "name": path.name, "id": meta.get("id"), "parent_id": meta.get("parent_thread_id"),
        "cwd": meta.get("cwd") or "", "kind": kind, "logical": logical, "logical_h": human_bytes(logical),
        "local_allocated": local_allocated(path), "local_allocated_h": human_bytes(local_allocated(path)),
        "age_days": round(age, 1), "last_turn_complete": completed, "linked": linked,
        "target": str(target) if target else None, "target_exists": target_exists, "backup": str(backup),
        "backup_exists": backup.is_file(), "backup_bytes": backup.stat().st_size if backup.is_file() else 0,
        "eligible": not reasons, "reasons": reasons, "error": error,
    }


def scan(codex_home: Path, min_age: float = 14, priority: str | None = None) -> dict:
    root = codex_home / "sessions"
    sessions = []
    if root.exists():
        for path in root.rglob("*.jsonl"):
            sessions.append(session_record(path, min_age, priority))
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
        "totals": totals, "volumes": available_volumes(), "sessions": sessions, "generated_at": int(time.time()),
    }


def append_manifest(volume: Path, archive_name: str, record: dict) -> str:
    manifest = volume / archive_name / "manifests" / "offload_manifest.jsonl"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush(); os.fsync(stream.fileno())
    return str(manifest)


def plan_offload(path_value: str, codex_home: Path, volume_value: str, archive_name: str, min_age: float, priority: str | None) -> dict:
    source, relative = lexical_session(path_value, codex_home)
    volume = mounted_volume(volume_value)
    if source.is_symlink() or not source.is_file():
        raise HarborError("Source must be a local regular session file")
    item = session_record(source, min_age, priority)
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
            age = float(q.get("min_age", ["14"])[0]); key = (age, priority or "")
            with self.app["cache_lock"]:
                cached = self.app.get("cache")
                if cached and cached["key"] == key and time.time() - cached["at"] < 8:
                    result = cached["value"]
                else:
                    result = scan(self.app["codex_home"], age, priority)
                    self.app["cache"] = {"key": key, "at": time.time(), "value": result}
            return self.send_json(200, result)
        if parsed.path == "/api/config": return self.send_json(200, {"token": self.app["token"], "version": VERSION, "priority": self.app["priority"]})
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
                saved = save_config(str(data.get("priority") or "")); self.app["priority"] = saved["priority"]
                self.app["cache"] = None
                return self.send_json(200, {"ok": True, "settings": saved})
            paths = data.get("paths") or []
            if not paths: raise HarborError("No sessions selected")
            results = []
            if self.path == "/api/plan":
                for path in paths: results.append(plan_offload(path, self.app["codex_home"], data["volume"], data.get("archive_name") or DEFAULT_ARCHIVE, float(data.get("min_age", 14)), data.get("priority") or None))
            elif self.path == "/api/offload":
                volume = mounted_volume(data["volume"]); archive = data.get("archive_name") or DEFAULT_ARCHIVE
                for path in paths:
                    plan = plan_offload(path, self.app["codex_home"], str(volume), archive, float(data.get("min_age", 14)), data.get("priority") or None)
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
    priority = load_config()["priority"]
    server = ThreadingHTTPServer(("127.0.0.1", args.port), HarborHandler); server.app = {"assets": assets, "token": token, "codex_home": codex_home, "priority": priority, "cache": None, "cache_lock": threading.Lock()}
    url = f"http://127.0.0.1:{server.server_port}/"
    print(json.dumps({"url": url, "version": VERSION, "codex_home": str(codex_home)}, ensure_ascii=False), flush=True)
    if args.open: threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--codex-home")
    sub = parser.add_subparsers(dest="command", required=True)
    scan_p = sub.add_parser("scan"); scan_p.add_argument("--min-age", type=float, default=14); scan_p.add_argument("--priority")
    serve_p = sub.add_parser("serve"); serve_p.add_argument("--port", type=int, default=48765); serve_p.add_argument("--open", action="store_true")
    audit_p = sub.add_parser("audit"); audit_p.add_argument("path")
    args = parser.parse_args()
    home = Path(args.codex_home or os.environ.get("CODEX_HOME", "~/.codex")).expanduser().absolute()
    try:
        if args.command == "scan": print(json.dumps(scan(home, args.min_age, args.priority if args.priority is not None else load_config()["priority"] or None), ensure_ascii=False, indent=2))
        elif args.command == "serve": serve(args)
        elif args.command == "audit": print(json.dumps(audit_one(args.path, home), ensure_ascii=False, indent=2))
    except (HarborError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
