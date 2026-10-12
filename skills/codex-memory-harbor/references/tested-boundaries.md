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

## Stable macOS privacy identity, 2026-09-03

- The pre-fix machine had two simultaneously running app copies with the same bundle ID: `/Applications/Codex Memory Harbor.app` and `~/Applications/Memory Harbor.app`. Both were ad-hoc signed, and the macOS TCC log explicitly reported that their recorded and current `cdhash` requirements did not match before prompting again for removable-volume access.
- Memory Harbor 0.4.3-beta.1 gives the renamed app and dashboard unique `com.alexsolar.memory-harbor` bundle IDs, adds the removable-volume usage description, signs both nested code bundles with one reusable local keychain identity, and rejects ad-hoc signing. The installer stops both legacy and current processes, retires the old app and launch agent recoverably, and pins the login item to the absolute canonical app path.
- Its local gate passed 30 unit tests, Python bytecode compilation, JavaScript syntax checks, plist validation, Swift compilation, nested signing, and strict bundle verification. Two consecutive clean builds produced the same designated requirements. After the first `authValue=2` removable-volume grant, a full reinstall and app restart kept that requirement and produced no second TCC prompt or code-requirement mismatch.

## Dashboard helper lifecycle repair, 2026-09-03

- A user-triggered dashboard failure was reproduced with an orphaned Python server from an older helper still holding fixed port `48765`; the port accepted TCP but returned an empty HTTP response. The new helper therefore could not become ready, displayed a generic-icon alert, and left its transparent window visible over the desktop.
- Memory Harbor 0.4.4-beta.1 gives every dashboard helper its own ephemeral loopback port, passes the helper PID to the server for parent-exit shutdown, closes the empty window after startup failure, packages the real app icon into the helper, labels the helper as `Memory Harbor`, and keeps the compact owner out of the Dock. The installer also terminates legacy server orphans by exact installed-script command path.
- Memory Harbor 0.4.4-beta.2 makes Simplified Chinese the default user-facing language across the Skill, native status card, dashboard actions, removable-volume permission explanation, CLI failures, frontend foundation, and handbook entry. The compact card now leads with accessible docked history (`accessible / docked`) instead of reclaimable bytes. Its fixture-only “深空智能港” prototype was verified in the in-app browser with navigation, search, command palette, evidence drawer wiring, and no console errors; it does not call `/api` or operate on real history. The 37-test suite, Python and JavaScript syntax checks, shell validation, Swift build, nested signing, installed-bundle strict signature check, and repository-to-installed Skill comparison passed. On the verification machine, the installed 0.4.4-beta.2 compact status reported 194 / 194 docked histories accessible.
- Memory Harbor 0.4.4-beta.3 replaces the prior control-room-style concept with a clean “未来记忆港” prototype derived again from the product north star. Primary navigation is reduced to `港湾 / 找回记忆 / 安全停泊`; connections, verification, settings, Runtime terms, and hashes move behind progressive disclosure. The fixture-only prototype passed real in-app-browser checks for narrow-window layout, natural-language recall filtering, memory detail sheets, the Command-K quick-find path, and a clean console. The installed native card now says `记忆都在 / 随时可以回来 / 194 / 194`, while the current production dashboard uses simpler Chinese task language without changing any migration endpoint or safety gate. The 37-test suite, Python and JavaScript syntax checks, shell validation, signed Swift build, installed-bundle strict signature verification, installed-Skill comparison, and helper-owned-server shutdown check passed. No docking, release, or restore action was executed during this visual verification.
- Its 33-test gate includes an ephemeral-port HTTP round trip and automatic server shutdown after a synthetic helper-parent exit. On the target Mac, the full dashboard rendered while a dummy process deliberately occupied `48765`; it used `127.0.0.1:55043`, displayed the mounted external target and live catalog, and `放回桌面` removed both helper and server while leaving only the compact owner running.

Do not describe unverified cases as supported. On a new machine or storage device, choose “同时保留本地备份” until restart and remount checks pass.

## Project media and safety hardening, 2026-10-12

- 0.4.5-beta.1 adds on-demand project storage plans for saved Codex projects, independently accounting for project media and task history. The normal scan does not recursively scan media. The dashboard supports directory selection, 100-item pagination, complete-plan export, explicit file docking, local backup retention/release, and receipt-verified restore.
- The 80-test gate passed, including real loopback HTTP plan/dock/restore requests, unauthorized source/target and expired-plan rejection, priority bypass rejection, source changes, target collisions, flush/receipt failure, corrupted external content, retained backups, source locks, unchanged legacy maintenance entrypoints, and distinct history/media capacity labels. Python/JavaScript/shell syntax and whitespace checks passed. The official Skill validator could not run because PyYAML was absent in both available Python runtimes; an independent Ruby YAML/frontmatter check passed instead.
- A disposable synthetic asset on the attached exFAT volume completed durable copy, SHA-256 readback, original-path link reads, independent verification, local release and restore. The synthetic scratch directories were removed after the test; no personal project asset or history was docked, released or restored during this update.
- History docking now uses exclusive destination creation, file/directory fsync, source signature/content and bounded open-handle rechecks, volume UUID rechecks, cross-process source locks, and recorded expected hashes for audit/release/restore. Two reads through the same corrupt link no longer count as verification. Protected projects come from server settings, not client overrides; unreadable protection settings and handle-check failures stop mutation.
- The installed app and helper were rebuilt and strictly signature-verified at version 0.4.5-beta.1; repository and installed Skill contents matched. The signing identity remains the existing stable identity.
- The installed dashboard's real project-plan view independently displayed about 25 GB of already-docked Ali task history and 9.2 GB of undocked media candidates. The 1.9 MB hero concerns newly eligible history across projects, not media. Opening the media plan selected zero files and retained the checked local-backup default; no actual docking was confirmed.
- This does not prove real-project full-batch, Codex restart/resume, physical unplug/remount, arbitrary editor hot reload, media-link volume rename repair, general filesystem metadata preservation, new Runtime support or abrupt-power-loss durability. Default project-media local backup retention remains on pending those independent checks.

## Shared parking engine and simpler existing UI, 2026-10-12

- 0.4.5-beta.2 routes history, project files and explicit frozen file lists through one byte-transaction engine. Existing history manifests, archive paths, rollback suffixes, protection rules and restore APIs remain compatible. The existing dashboard list switches between history and project files, shares one bottom docking action, and reuses the confirmation/progress dialogs; the separate project-plan dialog is removed.
- The 94-test gate passed with the explicit physical-volume smoke test enabled. It retains the prior 80 tests and adds fresh grouped handle checks, per-file readback/fsync counts, source changes, open handles before release, missing volumes, corrupt targets, receipt failures before/after release, accurate committed-prefix progress, first-error stopping, bounded large-file groups, fresh uncached UUID queries and bounded fail-closed fallback. A real loopback mixed history/file batch verified both original paths and restored through the legacy history and file APIs; duplicate submission returned the same job id.
- Two old/new disposable-fixture runs on the attached exFAT drive found 32 × 128 KiB release batches at 25.762/25.064 seconds before and 0.608/0.603 seconds after. Two × 64 MiB release batches were 2.109/2.264 seconds before and 1.392/1.573 seconds after. SHA-256 readback and fsync counts were unchanged; every result was independently audited and restored. Details and cache/order limitations: `docs/benchmarks/20261012-parking.md`. This is not physical-ceiling calibration or a real-project batch prediction.
- Browser verification exercised directory selection, shared confirmation, the checked project-backup default, cancellation without starting a real-file job, and zero-selection state. A fully isolated browser fixture completed docking, progress and restore. At 390 px width, header wrapping removed horizontal overflow; console checks were clean. Capacity switches with the content mode instead of showing history-only 1.9 MB as project media. Only read-only plans and cancelled confirmations touched real project metadata.
- The existing local-index benchmark passed at 1.831 ms recall p95 over 40 iterations; metadata scan took 2.352 seconds for 770 current sessions. This is not a measurement of frontmost interaction latency during transfer.
- Swift build, nested/stable signing, strict installed-bundle verification and version 0.4.5-beta.2 readback passed. The installed native card and helper rendered the new dashboard. The official Skill validator remained unavailable because PyYAML was missing; independent Ruby YAML/frontmatter validation passed. No new signing identity or privilege weakening was introduced.
- The new batch progress is in memory; durable manifests/receipts and local rollback copies remain recovery evidence. Server restart does not replay a job. Automatic physical calibration, adaptive concurrent transfer, power-loss recovery, project-media mount rename repair and a second Runtime Adapter remain unverified or unimplemented. Personal assets/history were not docked, released or restored by the agent during this update; the user retains control of the real batch.

## Single bilingual workbench, 2026-10-12

- 0.4.6-beta.1 uses one real API-backed project tree for history and on-demand media, with one review action. English and Simplified Chinese cover the web/native presentation and public README; technical evidence and user titles are not translated. The CLI keeps its existing stable language contract.
- 107 local tests passed with the disposable attached-drive test enabled. Browser fixtures exercised project protection, media docking with the checked local-copy default, exact terminal progress, receipt-backed restore, search, language/theme preservation and narrow layouts. Public screenshots contain only test fixtures. No personal batch was operated by the agent.
- Signed builds, strict installed verification and source/installed-Skill comparison passed. The installed helper rendered live read-only capacity/candidates; returning to desktop rendered 205/205 accessible histories on the native-material card. Native WebKit select sizing was visually checked and corrected. Official Skill validation remained unavailable due to missing PyYAML; independent YAML/frontmatter validation passed.
- The read-only index benchmark measured 2.216 ms p95 over 40 iterations; a 778-session metadata scan took 2.459 seconds. These are not transfer-time interaction or CPU/memory guarantees. No idle progress poll or decorative animation loop was introduced.
- This release does not newly verify private full batches, physical remount, Codex cold resume, arbitrary active workspaces, cloud storage or automatic associative memory. Detailed evidence and source-beta packaging limits: `docs/verification/0.4.6-beta.1.md`.

## Single window surface correction, 2026-10-12

- 0.4.6-beta.2 removes the nested workbench card and duplicate visible native title after installed-window feedback. The actual installed helper was visually reviewed, along with bilingual browser demo screenshots and a 390-pixel layout.
- 108 local tests passed with disposable attached-volume verification enabled; Swift typechecks, signed build, strict installed signature and source/installed-Skill comparison passed. Only presentation changed; no private storage operation occurred. Details: `docs/verification/0.4.6-beta.2.md`.
