# Memory Harbor product contract

Memory Harbor is a lightweight macOS companion for Codex. It finds large, inactive,
completed child-task histories and safely docks them outside the internal disk while
preserving the original path that Codex reads.

Version 0.3 also maintains a small local discovery catalog. This makes task identity,
project membership, integrity metadata, and external location searchable without
turning the catalog into a second copy of the conversation.

## User promise

- Show internal free space and Codex storage by project without reading conversation text.
- Recommend only completed child tasks that have been inactive for at least 30 days.
- Never automatically move main, current, open, incomplete, starred-project, or pinned-task history.
- Copy, size-check, SHA-256-check, then replace the original with an absolute link.
- Keep a local rollback copy until the user separately verifies and explicitly releases it.
- Restore a docked history to an ordinary local file at any time while its destination is available.

## Continuous development

An external drive that remains mounted at the same `/Volumes/...` path is transparent to
Codex: the session path under `~/.codex/sessions` remains present as an absolute symlink,
so normal reads follow it to the verified external copy. Disconnecting the drive does not
delete data, but docked history is temporarily unreadable until the same destination is
mounted again. Active development history always stays local.

## One-click optimization

The button ranks eligible history using both size and inactivity. The beta safety batch is
capped at 25 files or 5 GB, stops on the first error, and never releases rollback copies.
The user may adjust the recommendation before migration or repeat a verified batch.

## Information architecture

The organizer is one tree, not separate project and file inspectors:

`Codex storage -> saved project -> task session file`

Project membership comes from Codex's local project and task-assignment metadata. A task
without a saved-project assignment appears under a visibly distinct `Unclassified tasks`
branch even when its session metadata contains a working directory. Expanding a project
shows its individual session files, size, age, protection state, and task-level pin. Parent
checkboxes use mixed state when only some children are selected.

Task rows use the human-readable title already maintained by Codex. Opening the local detail
card lazily reads only that task's Codex-generated short preview and can deep-link back to the
original task in Codex. The inventory never scans full prompt or response bodies.

The scanner reads project assignment metadata, task titles, timestamps, paths, sizes,
completion events, and session identifiers. It does not read or index conversation bodies.

## Local discovery catalog

The rebuildable SQLite catalog lives under `~/.codex/memory-harbor/`. SQLite FTS5 indexes
task titles, project names, identifiers, working directories, and agent paths. Full prompts,
responses, tool output, credentials, and browser state are excluded.

Mounted external manifests can rebuild the catalog. Catalog rows distinguish whether the
original source entry exists and whether the external target is currently available. An
offline result may still be discovered, but opening raw evidence requires its volume.

External volumes are recorded with the persistent UUID exposed by macOS when available.
A broken absolute link may be repaired only when the UUID, archived relative path, byte
length, and SHA-256 content hash agree. A mount path or display name alone is insufficient.

## Storage provider boundary

The API accepts a `storage_target` with `provider` and `location` fields. Version 0.2 ships
only the `external_volume` provider. The UI exposes `Memory Harbor Cloud` as unavailable,
not as a simulated feature.

Future cloud providers (S3-compatible storage, OSS, or another service) must implement the
same stages: availability, capacity, upload, integrity verification, materialized local
read path or managed cache, restore, and explicit local rollback release. Credentials must
live in macOS Keychain or the provider's supported authorization flow, never in manifests,
settings, logs, or repository files.

Cloud storage must not replace a local history path with a network URL. It must first
provide a verified local materialization/cache contract and define offline behavior, so a
slow or disconnected network cannot silently corrupt Codex continuity.

## Adaptive transfer roadmap

Transfer performance is a storage-property problem, not a single hard-coded concurrency
setting. A later performance release will benchmark the selected target with a bounded,
non-destructive probe and classify its latency and sequential throughput. The transfer
planner can then select a conservative chunk size, worker count, checksum pipeline, and
local read-cache policy for fast SSDs, slower flash drives, rotational disks, and future
network or cloud targets.

The safety order is invariant: copy, durable flush, size verification, content verification,
then link replacement. Performance work may pipeline independent files or hashing, but it
must never weaken those gates, saturate the foreground Codex workload, or treat a synthetic
benchmark as proof of production reliability. The UI should expose the detected storage
class and estimated completion time without making unsupported speed claims.

## Lifecycle

`Local -> Docked with local rollback -> Docked -> Restored local`

The destructive transition from `Docked with local rollback` to `Docked` always requires a
fresh, explicit user confirmation after integrity and remount verification.
