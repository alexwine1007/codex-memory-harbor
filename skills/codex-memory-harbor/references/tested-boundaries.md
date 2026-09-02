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

## Traceable recall and performance isolation, 2026-09-03

- Memory Harbor 0.4.0-beta.1 passed 22 local unit tests, Python bytecode compilation, JavaScript syntax validation, Swift compilation, nested-helper code signing, and full app-bundle signature verification. Tests cover provenance, secret redaction, inherited-history and tool-output exclusion, idempotent indexing, offline recall, compact-summary privacy, and the rule that foreground recall cannot probe external storage or hash raw evidence.
- Five currently linked child tasks were backfilled: four had trustworthy task boundaries and produced 11 compact outward-report fragments; one legacy child record remained metadata-only by design. Repeating the same build skipped all five unchanged sources, completed in 0.684 seconds, and reported no errors.
- A real content query for `强约束` found `ep03 evidence audit`, identified the match as an outward task report, and retained the exact source line. With the external evidence path unavailable, the local-index test still returned the same provenance rather than silently reading another source.
- The dashboard rendered the content match, automatically expanded its unclassified-task branch, displayed the evidence excerpt, and reported four content-recallable tasks. No browser-console error was observed.
- After foreground queries were moved to strict read-only SQLite connections, the final 100-run gate measured 1.119 ms median and 1.528 ms p95. A real 516-session metadata scan measured 0.568 seconds. The local catalog was 6,389,760 bytes.
- The installed 0.4 companion now uses a native Cocoa compact card. In the compact state,
  `top` measured 0.0% CPU and about 26 MB memory, with no Python dashboard server and no
  helper process running. Opening the dashboard launched a separately signed helper plus the
  local server; returning it to the desktop terminated both processes, and the compact owner
  remained at the saved desktop position. The installed helper still rendered the 516-item
  tree and the EP03 content match before termination.
- Keyword retrieval is only a deterministic traceability baseline. Automatic associative recall, semantic false-positive evaluation, and topic-change routing are not yet implemented and must not be described as shipped.

## Migration completion semantics, 2026-09-03

- A real ten-task batch totaling 5,368,656,618 bytes was first copied, linked, and verified against Alex's Disk. Source link, external target, and local rollback hashes matched for all ten tasks before release.
- After the user authorized finalization, all ten local rollback copies were removed. Internal free space rose from about 854 MB to 5.8 GB. A second audit found every source link and external target readable with no local rollback present.
- Codex then cold-read all ten task histories from `notLoaded` state after local release. This proves external-only reads for that batch in the same runtime. A restart plus remount check for this ten-task batch remains pending; the earlier one-task pilot is still the only case with both checks completed.
- Memory Harbor 0.4.1-beta.1 passed 25 local tests, including the real `/api/migrate` route, automatic local release after an independent re-audit, and preservation of the local backup when that re-audit fails. Python bytecode compilation, JavaScript syntax validation, Skill validation, Swift compilation, nested-helper signing, and full app-bundle signature verification also passed.
- The installed 0.4.1 app rendered the default automatic-release explanation, exposed an unchecked “同时保留本地备份” option, toggled that option correctly, and returned to the task list without starting a migration when the confirmation was cancelled. The final performance gate measured 1.266 ms recall p95 and a 1.147-second scan of 518 sessions.
- A subsequent 11-task, 5.0 GB batch exposed a duplicate-submit race: one migration flow completed every task while another flow retried the first item and reported a missing rollback. Post-run inspection found all 11 targets and links verified, all 11 local rollbacks absent, linked count increased from 15 to 26, and internal free space increased from 7.8 GB to 12.7 GB. No task was lost; the failure was a concurrent UI/API status bug.
- Memory Harbor 0.4.2-beta.1 adds a frontend operation guard, serializes mutation APIs, and treats a repeated request for an already verified migrated task as idempotent success. Its 26-test gate includes two simultaneous `/api/migrate` requests: both return success, only one manifest record is written, the source remains readable, and no local rollback remains.

Do not describe unverified cases as supported. On a new machine or storage device, choose “同时保留本地备份” until restart and remount checks pass.
