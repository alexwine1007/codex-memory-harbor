# Contributing to Memory Harbor

English · [简体中文入门](README.zh-CN.md)

Small, evidence-backed contributions are welcome: translations, accessibility, recovery tests, independent device validation and new runtime adapters.

## Development

macOS 13+, Python 3.9+ and Node 18+ are sufficient for the test suite. Apple's Command Line Tools are needed to compile the native app. No web framework or package installation is required.

```bash
python3 -m unittest discover -s tests -q
node --check skills/codex-memory-harbor/assets/dashboard/app.js
./scripts/build_macos_app.sh
```

For browser QA, `python3 tests/ui_fixture_server.py` serves the real dashboard and backend against disposable local files with mocked removable-volume identity. It never operates on personal history. Close the server to remove its temporary fixtures. The fixture is not a physical removable-device test.

The optional physical-volume regression requires an explicitly selected test volume:

```bash
MEMORY_HARBOR_TEST_VOLUME=/Volumes/YOUR_TEST_DRIVE python3 -m unittest discover -s tests -q
```

It creates disposable scratch data. Never point a test at an unapproved device or pass personal files as fixtures.

## Pull requests

- Keep each change scoped, add regression tests and document its evidence boundary.
- Preserve original paths, legacy receipts, local rollback recovery and idempotency.
- Never trade SHA-256, independent readback, source/volume checks or durable writes for speed.
- Do not scan an entire archive, invoke models or continuously poll disks in normal work.
- UI changes need a real browser screenshot at desktop and narrow widths, keyboard checks and both languages. Use synthetic data only in public screenshots.
- State whether a result is a unit test, disposable browser fixture, physical-volume test, runtime restart/remount check or user acceptance. These are not interchangeable.
- New runtime adapters must have their own read/open/resume evidence before being advertised.

## Translations

See [docs/i18n.md](docs/i18n.md). Do not translate user titles, filenames, paths or original evidence. Preserve every warning and placeholder. Translation contributions do not authorize weakening safety wording.

## Privacy

Never submit private conversations, browser profiles, credentials, signing-key material, full session logs or identifiable filesystem screenshots. Redact issue reproductions. Sensitive vulnerabilities should not be posted in a public issue; see [SECURITY.md](SECURITY.md).
