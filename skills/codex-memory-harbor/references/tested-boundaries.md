# Tested boundaries

## Verified on macOS, 2026-09-02

- One old child-task JSONL was copied to an exFAT volume and matched by byte size and SHA-256.
- An absolute symlink at the original path resolved to that external file.
- A local rollback copy remained byte-identical.
- Codex reported the child task as `notLoaded`, then read it successfully by task id and paged into older completed turns. This is evidence of an on-demand disk read rather than a response copied from the active task context.
- The CLI refuses a main task and requires an old child task, a completed last turn, and no open file handles.

## Not yet verified

- Rediscovery after fully quitting every Codex process and reopening the app.
- Behavior after physically unplugging and remounting the external disk.
- A production batch containing hundreds of linked session files.
- Active session writes directly to external storage. This project intentionally does not support that mode.

Do not describe unverified cases as supported. Preserve rollback copies until the local machine passes its own restart and remount checks.
