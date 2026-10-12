# External storage and Codex continuity — clarification, 2026-10-13

## Public contract

Use an always-connected USB flash drive or external SSD/HDD to extend Mac storage. Eligible completed child histories and cold media are copied and verified, retaining original paths for reading/reuse while connected. Active main tasks, code, documents and runtime environments stay local. Reading old evidence is not a guarantee that every old child agent can resume directly.

## Historical evidence reviewed, not newly performed here

The [tested-boundaries record](../../skills/codex-memory-harbor/references/tested-boundaries.md) reports:

- **2026-09-02:** one exFAT child-history pilot; Codex task-id read of unloaded history and earlier turns; same-task reads after full runtime quit/restart and safe volume eject/disconnect/remount. Original-path, target and rollback checks matched.
- **2026-09-03:** four unloaded child histories read from another active task; later ten external-only histories cold-read after local rollback release. The ten-task batch did not receive separate restart/remount acceptance.
- **2026-09-03 restriction:** old multi-agent v2 child histories were readable by `thread/read`, but direct `thread/resume` failed because their parent must be resumed/hydrated first. Original-path readability does not bypass this runtime restriction.

These observations apply to the recorded machine, volume and then-current Codex runtime, not every USB flash drive, current runtime version, active workspace or editor.

## Fresh read-only audit

One already-docked history was located through the local catalog. Its original path is a symlink to an online external target. Two independent streamed reads—one through the original path, one through the external path—matched the recorded SHA-256. No history was migrated, released, restored, modified or sent to a model. Personal task identity, source/target paths, device identifiers, body and digest are deliberately omitted here.

This is byte-path evidence, **not a native Codex resume test**. A current app connector read attempt returned `thread/items/list is not supported yet`; it did not supply new native-read evidence and is not proof of a storage failure. No runtime restart, physical remount or model turn was performed in this clarification.

## Changes and checks

Chinese/English introductions and launch drafts now name USB flash drives and external SSD/HDDs, state the continuity goal, and separate verified reads from unaccepted direct continuation. Documentation-contract tests prevent losing those distinctions. Storage engine and app version are unchanged. Broader continuation/device acceptance remains independent work.

Local gate: **134 tests passed** with the owned disposable attached-volume regression enabled; new documentation contract, JavaScript/shell syntax and whitespace checks passed. This gate does not turn the historical runtime observations into a new direct-resume acceptance.
