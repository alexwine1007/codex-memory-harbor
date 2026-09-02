# Codex Memory Harbor · 记忆港

![Memory Harbor logo](skills/codex-memory-harbor/assets/dashboard/memory-harbor-logo-v4.png)

Codex Memory Harbor safely docks old Codex **child-task session logs** on a permanently attached external drive while preserving their original paths through verified symlinks.

Version 0.2 introduces a storage-provider boundary: external volumes work today,
while cloud storage is deliberately shown as a future provider until verified local
materialization, offline behavior, integrity checks, and credential handling exist.
See [PRODUCT.md](PRODUCT.md) for the product and continuity contract.

It ships as three pieces that share one safety model:

- a Codex Skill for guided audits and recovery;
- a local-only visual dashboard for inventory, dry runs, offload, audit, restore, and finalization;
- a lightweight macOS desktop app that keeps the dashboard one click away.

> Beta: this project relies on a filesystem behavior that is not an official Codex storage contract. Keep rollback copies until you have tested a full Codex restart and a drive remount on your machine.

## Why

Codex session JSONL files are history, recovery, and audit evidence—not disposable cache. They can grow large, especially when child agents do media or repository work. Deleting them blindly saves space but destroys provenance. Moving them blindly breaks the path Codex expects.

Memory Harbor uses a transactional sequence:

1. classify the session and refuse main tasks;
2. require age, last-turn-complete, and no-open-handle checks;
3. copy to the external volume;
4. verify byte size and SHA-256;
5. retain the local file as a rollback copy;
6. atomically place an absolute symlink at the original path;
7. delete the rollback copy only after a separate, explicit finalization.

## Quick start

```bash
python3 skills/codex-memory-harbor/scripts/harbor.py scan
python3 skills/codex-memory-harbor/scripts/harbor.py serve --open
```

The server binds only to `127.0.0.1`, uses a per-process action token, and never reads browser credentials.

### Build the macOS app

```bash
./scripts/build_macos_app.sh
open "dist/Codex Memory Harbor.app"
```

The app expects the Skill at `~/.codex/skills/codex-memory-harbor`. Set `CODEX_HARBOR_SCRIPT` to override that path.

### Install the desktop companion

```bash
./scripts/install_macos.sh
```

Pass `--login-item` to reopen the compact card after login. The companion is a desktop-layer window: it can be moved, stays out of normal window switching while compact, and expands into the dashboard on demand.

It is intentionally not advertised as a native WidgetKit extension. Registering a third-party WidgetKit extension requires full Xcode and a valid Apple code-signing identity; the current beta uses only the tools already present on a standard developer Mac.

## Safety boundaries

- Main task logs are never eligible.
- The current task and open files are never eligible.
- Logs newer than the configured minimum age (30 days by default) are never eligible.
- Users can star whole projects or individual important sessions for permanent local retention; those pins override age.
- Batch operations stop on the first failure.
- “Offloaded” does not mean internal space was reclaimed while a local rollback exists.
- If the external drive is unavailable, links are visibly reported as unavailable.

### Retention model

Eligibility is the intersection of machine safety and user intent:

```text
old enough AND child task AND last turn complete AND not open
AND project not starred AND session not starred
```

The 30-day threshold is only a conservative default. A star on an important project or individual session wins over time and keeps it local indefinitely. No personal project name or path is built into the public repository.

See [tested-boundaries.md](skills/codex-memory-harbor/references/tested-boundaries.md) for the exact evidence behind the current beta label.

## Privacy

The dashboard exposes metadata required to manage local sessions: Codex's task title, path, working directory, task id, parent id, age, and size. A user-triggered detail card reads only Codex's existing short preview and can open the original task. It does not scan or display full prompt/response bodies. Nothing is uploaded by this project.

## License

MIT. See [LICENSE](LICENSE).
