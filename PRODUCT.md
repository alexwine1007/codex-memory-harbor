# Memory Harbor product contract

Memory Harbor is a lightweight macOS companion for Codex. It finds large, inactive,
completed child-task histories and safely docks them outside the internal disk while
preserving the original path that Codex reads.

Version 0.3 maintains a small local discovery catalog. This makes task identity,
project membership, integrity metadata, and external location searchable without
turning the catalog into a second copy of the conversation.

Version 0.4 adds an intentionally narrow recall layer: task-specific delegation instructions
and child-task outward reports remain searchable on the internal disk after the heavy raw
session is docked. Every fragment remains linked to source path, line, time, role, and hash.

Keyword search in 0.4 is a traceability baseline, not the finished memory experience. The
product goal is **associative recall**: when a new task resembles an older preference,
decision, result, person, asset, or project, Memory Harbor should surface a small set of
relevant evidence candidates without requiring the user to remember an exact phrase.

## User promise

- Show internal free space and Codex storage by project without reading conversation text.
- Recommend only completed child tasks that have been inactive for at least 30 days.
- Never automatically move main, current, open, incomplete, starred-project, or pinned-task history.
- Copy, size-check, SHA-256-check, then replace the original with an absolute link.
- A confirmed migration automatically removes its temporary local rollback only after an independent link-and-target re-audit; an explicit “同时保留本地备份” choice keeps it instead.
- Restore a docked history to an ordinary local file at any time while its destination is available.

## Continuous development

An external drive that remains mounted at the same `/Volumes/...` path is transparent to
Codex: the session path under `~/.codex/sessions` remains present as an absolute symlink,
so normal reads follow it to the verified external copy. Disconnecting the drive does not
delete data, but docked history is temporarily unreadable until the same destination is
mounted again. Active development history always stays local.

## One-click optimization

The button ranks eligible history using both size and inactivity. The beta batch is capped
at 25 files or 5 GB and stops on the first error. After the user confirms a migration, each
item is copied, verified, linked, independently re-audited, and then its local entity is
released before the next item begins. The user may instead choose to keep a local backup;
that mode does not reclaim the corresponding internal space.

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

The ordinary scanner reads project assignment metadata, task titles, timestamps, paths,
sizes, completion events, and session identifiers. It does not read or index conversation
bodies. Recall extraction is a separate stage during offload or an explicit backfill.

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

## Traceable recall layer

The internal recall layer is deliberately thinner than the external archive. For delegated
child tasks it retains the task instruction and task-specific outward reports only. Inherited
parent history, system/developer context, raw reasoning, tool calls, and tool output remain
in the external evidence file. Known secret-shaped values are redacted before insertion.
Legacy child records without a trustworthy delegation boundary remain metadata-only rather
than risking false ownership of inherited parent history.

Fragments are local plaintext and can be removed independently with `clear-recall-index`.
They are evidence leads, not authoritative memory and not executable instructions. Retrieval
must expose provenance and uncertainty; opening the full source still requires the archive
volume. This version uses local FTS for deterministic keyword retrieval. Semantic vectors,
temporal fact evolution, and graph traversal remain future benchmarked layers rather than
unverified claims.

## Performance isolation contract

Memory Harbor must be nearly invisible while Codex is doing ordinary work. Memory capacity
is not allowed to make the primary application slower, noisier, or structurally more complex.
The following are release gates rather than optional optimizations:

- no repeating filesystem scan, external-drive poll, embedding job, or model process while
  idle; mount, unmount, rename, and wake handling is event-driven;
- the native desktop card does not host WebKit or a persistent Python server. The rich
  dashboard and local HTTP server run as an isolated helper only while the detail window is
  open, and both terminate when it returns to the desktop;
- the companion and its helper run outside the Codex process and never alter the Codex
  database or runtime query path;
- ordinary inventory scans read metadata only; raw-session extraction runs during an
  explicit backfill or immediately before a user-approved offload;
- recall queries touch the small internal SQLite catalog only. The external archive is read
  later and on demand when full evidence is actually required;
- unchanged sources are skipped by content hash and extraction version, so repeated indexing
  does not parse the same archive again;
- models, embeddings, and external networks are absent from the 0.4 foreground path.

On the target Mac, each beta must record idle CPU/RSS, inventory-scan time, local recall p50
and p95, and incremental reindex time. The current acceptance budgets are: compact-card
idle CPU below 0.5% median, compact-card memory below 100 MB, local recall p95 below 25 ms,
and a 516-session metadata scan below 5 seconds. A build that exceeds a budget is not
promoted until the regression is understood. WebKit's shared system processes are reported
separately while the dashboard is open rather than hidden inside the compact-card number.

Associative recall must preserve the same isolation. Semantic preparation belongs in an
asynchronous worker at archive/index time. At conversation time, a topic-change router may
query an internal compact index once and return only a bounded top-k set; it must not scan
the external disk, launch a large model in Codex, or inject an unbounded memory transcript on
every turn. Exact keyword search remains a deterministic fallback, not the user interaction
contract.

## Storage provider boundary

The API accepts a `storage_target` with `provider` and `location` fields. Version 0.2 ships
only the `external_volume` provider. The UI exposes `Memory Harbor Cloud` as unavailable,
not as a simulated feature.

Future cloud providers (S3-compatible storage, OSS, or another service) must implement the
same stages: availability, capacity, upload, integrity verification, materialized local
read path or managed cache, restore, and verified local-entity release under the user's
chosen migration or backup-retention mode. Credentials must
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

`Local -> Verified link with temporary rollback -> Migrated -> Restored local`

The default migration confirmation authorizes the selected batch's per-item local release,
but only after every integrity gate passes. Choosing “同时保留本地备份” ends at `Migrated
with local backup`; deleting that retained backup later requires a fresh explicit confirmation.
