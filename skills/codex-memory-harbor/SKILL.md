---
name: codex-memory-harbor
description: Audit, visualize, offload, verify, restore, and reclaim completed Codex child-task session logs on a permanently attached external drive. Use when Codex history consumes local disk space or the user asks to open the Memory Harbor dashboard.
---

# Codex Memory Harbor

Treat Codex session JSONL as recovery and audit evidence, not cache.

## Choose a mode

- For a visual inventory or user-driven migration, run `python3 scripts/harbor.py serve --open`.
- For a quick read-only report, run `python3 scripts/harbor.py scan`.
- For automation or diagnosis, use the CLI subcommands shown by `python3 scripts/harbor.py --help`.

## Safety contract

- Never offload main-task logs, the current task, a file with open handles, a session whose last turn is not complete, or a session inside the configured priority project.
- Default to 14 days minimum age and dry-run mutations first.
- Copy, size-check, and SHA-256-check before replacing the source with an absolute symlink.
- Keep `.offload-local-backup` until the user has verified Codex cold-reading and, preferably, a full restart plus drive remount.
- Finalization is the only step that reclaims the rollback copy. Require explicit authorization immediately before it.
- Stop a batch on the first failure. Never silently skip a verification error.
- Do not move the whole `sessions` root or active main tasks.

Read [tested boundaries](references/tested-boundaries.md) before describing restart, remount, or large-batch support.
