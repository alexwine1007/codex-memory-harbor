# Tested boundaries

## Verified on macOS, 2026-09-02

- One old child-task JSONL was copied to an exFAT volume and matched by byte size and SHA-256.
- An absolute symlink at the original path resolved to that external file.
- A local rollback copy remained byte-identical.
- Codex reported the child task as `notLoaded`, then read it successfully by task id and paged into older completed turns. This is evidence of an on-demand disk read rather than a response copied from the active task context.
- After fully quitting and reopening the current `/Applications/ChatGPT.app` Codex desktop runtime, its newly started app server rediscovered and read the same externally stored child task by task id.
- After the user safely ejected, disconnected, and remounted the exFAT volume at the same mount path, the absolute symlink resolved again, Codex read the child task again, and source, target, and rollback SHA-256 values still matched.
- The CLI refuses a main task and requires an old child task, a completed last turn, and no open file handles.

## Not yet verified

- A production batch containing hundreds of linked session files.
- Active session writes directly to external storage. This project intentionally does not support that mode.

## Small-batch verification, 2026-09-03

- Four completed, unclassified child tasks totaling about 756.5 MB were migrated through the installed macOS app.
- Every task retained a local rollback copy; every external target existed; source-link, target, and rollback SHA-256 values matched.
- From a different active Codex task, Codex loaded all four offloaded tasks by task id while each reported `notLoaded`, and returned an older turn from each. This verifies cross-task, on-demand reads for the small batch.
- Restart and volume-remount verification for this four-task batch remains pending. The earlier one-task pilot is still the only batch with both checks completed.

## Old multi-agent child-task viewing, 2026-09-03

- Two migrated multi-agent v2 child tasks could still be read by `thread/read`, but Codex desktop failed when their deep links attempted `thread/resume`. Codex logged: `cannot resume an unloaded multi-agent v2 sub-agent through its parent; resume the parent first, or use thread/read to inspect it`.
- This is a Codex child-task hydration boundary, not evidence of external-drive, symlink, or checksum failure.
- Memory Harbor 0.2.3-beta.1 detects these sub-agent records, removes the misleading direct-open action, and instead exposes their task-specific outward reports on demand while excluding inherited parent history and raw tool output.
- On the two affected tasks, the in-app record view recovered the correct task identities (`ep03 evidence audit`, `ep04 starter audit`) and their final reports from the external targets. Ordinary user tasks retain the direct Codex-open action; sub-agent records provide an action to open the owning parent task.

## Local discovery and volume identity, 2026-09-03

- Memory Harbor 0.3.0-beta.1 passed 15 local unit tests, Python bytecode compilation, and JavaScript syntax validation.
- A fresh local SQLite catalog remained searchable after its source session file disappeared. A mounted external manifest rebuilt a missing catalog entry without indexing conversation bodies.
- A synthetic renamed-volume test repaired a broken absolute symlink only when persistent volume UUID, byte length, and SHA-256 all matched.
- On this Mac, a real scan cataloged 516 task records, imported four relevant external manifest records, and found two EP03 records by title. The attached Alex's Disk exposed persistent UUID `416F6307-4C31-3150-8734-75B3C9733EDB`.
- A physical volume rename followed by automatic link repair has not yet been performed. The link-repair result above is unit-test evidence, not a claim that this destructive-environment scenario has been accepted on the user's drive.

Do not describe unverified cases as supported. Preserve rollback copies until the local machine passes its own restart and remount checks.
