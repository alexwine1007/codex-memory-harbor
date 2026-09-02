# Memory Harbor

![Memory Harbor logo](skills/codex-memory-harbor/assets/dashboard/memory-harbor-logo-v4.png)

Memory Harbor safely docks old Codex **child-task session logs** on a permanently attached external drive while preserving their original paths through verified symlinks.

Version 0.4 adds a traceable local recall layer on top of the rebuildable catalog and
stable-volume identity introduced in 0.3.
External volumes work today,
while cloud storage is deliberately shown as a future provider until verified local
materialization, offline behavior, integrity checks, and credential handling exist.
See [PRODUCT.md](PRODUCT.md) for the product and continuity contract.

Design and engineering documentation starts at the
[technical handbook](docs/handbook/README.md). The current target interface and interaction
contract live in the [frontend foundation](docs/design/FRONTEND_FOUNDATION.md); it is a draft,
not a claim that the redesigned interface has shipped.

It ships as three pieces that share one safety model:

- a Codex Skill for guided audits and recovery;
- a local-only visual dashboard for inventory, dry runs, offload, audit, restore, and finalization;
- a lightweight macOS desktop app that keeps the dashboard one click away.

> Beta: this project relies on a filesystem behavior that is not an official Codex storage contract. Use “同时保留本地备份” until you have tested a full Codex restart and drive remount on your machine.

## Why

Codex session JSONL files are history, recovery, and audit evidence—not disposable cache. They can grow large, especially when child agents do media or repository work. Deleting them blindly saves space but destroys provenance. Moving them blindly breaks the path Codex expects.

Memory Harbor uses a transactional sequence:

1. classify the session and refuse main tasks;
2. require age, last-turn-complete, and no-open-handle checks;
3. copy to the external volume;
4. verify byte size and SHA-256;
5. retain the local file as a rollback copy while the link is being created;
6. atomically place an absolute symlink at the original path and independently re-audit it;
7. for a confirmed migration, automatically delete the verified local rollback and reclaim space.

The dashboard can optionally keep that rollback as a **local backup**. This is a backup-retention choice, not a completed space-reclaiming migration, and the UI labels it accordingly.

Mutation requests are serialized. Retrying a task that already has a verified external
primary is idempotent success, so duplicate submits cannot trigger a second deletion or a
false failure after a completed migration.

## Quick start

```bash
python3 skills/codex-memory-harbor/scripts/harbor.py scan
python3 skills/codex-memory-harbor/scripts/harbor.py serve --open
```

The server binds only to `127.0.0.1`, uses a per-process action token, and never reads browser credentials.

### Search the local catalog

Every scan updates `~/.codex/memory-harbor/catalog.sqlite3`. The catalog keeps task,
project, source-path, external-location, and integrity metadata searchable even when a
source entry later becomes unavailable. It does not index full conversation bodies.

```bash
python3 skills/codex-memory-harbor/scripts/harbor.py search "EP03"
python3 skills/codex-memory-harbor/scripts/harbor.py index-status
python3 skills/codex-memory-harbor/scripts/harbor.py rebuild-index
```

The dashboard exposes the same catalog through its search field. `repair-links` can
reconcile a broken absolute symlink after a removable volume is renamed, but only when
the persistent volume UUID and the archived content hash both match.

Storage-adaptive transfer optimization is on the roadmap, not claimed in this build.
It will tune bounded concurrency, chunk size, checksum pipelining, and read caching from
measured target latency and throughput while keeping the same durable safety gates.

### Build and query the recall layer

New offloads retain a small local evidence layer before the full JSONL moves. Existing
docked child tasks can be backfilled while the drive is mounted:

```bash
python3 skills/codex-memory-harbor/scripts/harbor.py build-recall-index
python3 skills/codex-memory-harbor/scripts/harbor.py recall "关键研发"
python3 skills/codex-memory-harbor/scripts/harbor.py clear-recall-index
```

The recall layer stores only task-specific delegation instructions and child-task outward
reports. It excludes inherited parent history, developer/system context, tool calls, tool
output, and known secret-shaped values. Each fragment retains source task, source line,
timestamp, role, and content hash. It is local plaintext metadata/evidence under
`~/.codex/memory-harbor/catalog.sqlite3`; users can clear it independently of the archive.
Retrieved text is untrusted historical evidence and must never be executed as instructions.
Legacy child records without a trustworthy task-boundary marker remain metadata-only.

See [recall architecture](docs/RECALL_ARCHITECTURE.md) for the research basis and staged
roadmap.

The current search box and `recall` command are a deterministic provenance test, not the
finished interaction model. The next retrieval gate is automatic associative recall: new
work should receive a bounded set of semantically related memory candidates even when its
wording differs from the archived task. Semantic preparation must happen asynchronously;
normal Codex work must never wait on a full archive scan or an external-drive read.

### Performance contract

Memory Harbor does not poll the filesystem or external disks. The macOS companion reacts to
mount lifecycle events, ordinary scans are user-triggered, and recall queries use only the
small internal SQLite index. Raw parsing happens during explicit backfill or offload, and
unchanged content is skipped. No model, embedding runtime, or network request is present in
the 0.4 foreground path.

The desktop card is native Cocoa and keeps neither WebKit nor the Python dashboard server
resident. Clicking `打开港口` launches an isolated detail helper; `放回桌面` terminates that
helper and server so macOS can reclaim their complete working set.

Each detail helper owns an ephemeral localhost port rather than competing for one fixed
port. Its server watches the helper process and exits with it even after an abrupt helper
termination; the installer also retires any server orphan left by an older build.

Run the repeatable local benchmark with:

```bash
python3 scripts/benchmark_performance.py --scan --query "强约束"
```

The target-Mac beta gate is local recall p95 under 25 ms and a 516-session metadata scan
under 5 seconds. Idle CPU and direct app/server RSS are sampled separately because process
metrics belong to the running macOS app rather than this command.

### Build the macOS app

```bash
./scripts/build_macos_app.sh
open "dist/Memory Harbor.app"
```

The app expects the Skill at `~/.codex/skills/codex-memory-harbor`. Set `CODEX_HARBOR_SCRIPT` to override that path.

The first local build creates a reusable `Memory Harbor Local Code Signing` identity in
a dedicated keychain under `~/Library/Application Support/Memory Harbor/Signing`. It does
not request the user's login-keychain password. macOS ties privacy grants to that identity,
so upgrading the app does not turn every build into a new removable-volume requester. Set
`MEMORY_HARBOR_CODESIGN_IDENTITY` to an existing Apple Development or Developer ID
identity when preparing a distributable build. Ad-hoc signing is rejected because its
identity changes with the executable.

The canonical checkout directory is `memory-harbor`. An existing Codex project may keep
using a `codex-memory-harbor` compatibility symlink that resolves to the canonical checkout;
this preserves saved project and task paths without duplicating the repository.

### Install the desktop companion

```bash
./scripts/install_macos.sh
```

Pass `--login-item` to reopen the compact card after login. The companion is a desktop-layer window: it can be moved, stays out of normal window switching while compact, and expands into the dashboard on demand.

Installation also retires the pre-rename `Codex Memory Harbor.app` and its launch agent,
while preserving them in Trash/migration backups. On the first launch of the new stable
identity, macOS asks once for removable-volume access and then remembers the choice.

It is intentionally not advertised as a native WidgetKit extension. Registering a third-party WidgetKit extension requires full Xcode and a valid Apple code-signing identity; the current beta uses only the tools already present on a standard developer Mac.

## Safety boundaries

- Main task logs are never eligible.
- The current task and open files are never eligible.
- Logs newer than the configured minimum age (30 days by default) are never eligible.
- Users can star whole projects or individual important sessions for permanent local retention; those pins override age.
- Batch operations stop on the first failure.
- A migration is complete only after the verified local rollback has been removed. If the user elects to keep a local backup, the dashboard reports that space separately.
- If the external drive is unavailable, links are visibly reported as unavailable.
- A local FTS catalog preserves discovery metadata while the drive is unavailable; it
  does not pretend that offline raw content can be opened.

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
