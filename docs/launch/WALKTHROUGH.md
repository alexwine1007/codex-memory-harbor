# Walkthrough evidence / 导览的证据边界

These two **30-second silent videos** are captioned edits of observed UI states, **not continuous screen recordings or transfer-speed measurements**. English and Simplified Chinese captions are supplied. Original sample task descriptions remain Chinese in the English UI, just as real user content is not automatically translated.

## Source

- Actual dashboard code served by `tests/ui_fixture_server.py`; all files were created in its temporary test directory.
- Three completed synthetic child histories plus one synthetic media-byte fixture, about 5 KiB total. The `.mp4` fixture is test bytes, not a claimed film.
- Drive enumeration, UUID/mount identity and capacity are simulated in that fixture. Byte copies, fsync, hashes, original-path links and restore run against real temporary files. No physical drive/Codex-resume claim follows from this video.
- The separate `scripts/try_harbor.py` trial was run on a real attached volume with real UUID/handle checks. Its 128 KiB original-path sample read, local rollback and restore all passed; the sample was not private history. This is independent byte-layer evidence, not the video's simulated environment.
- Personal drive names, project paths, history and capacity are not used in public screenshots. The fixture publishes a fixed 16 GiB local-free example and 1 GiB demo-drive-free example.

## Sequence, 5 seconds each

1. Product cover and source-beta label.
2. Inspect suggestions; main/active work is kept local.
3. Exact 3-history + 1-file confirmation, with local retention checked.
4. Completed 4/4 verification with **no local copies removed**. Before restoration, original paths resolved to targets. Chinese-run independent hashes were `24a630edacfa`, `3b4b5d4802b4`, `d48ac69004ad`, `084686b799a8` (prefixes). English used a fresh fixture; its prefixes were `24a630edacfa`, `2b7bd8d7d1e6`, `b6046c569b97`, `f60bbbc5fd51`.
5. Receipt-backed restoration entry. Restoration was actually confirmed after the capture; all four source files were regular files again with the same hash prefixes. Do not interpret a button screenshot alone as proof of completion.
6. Safe first-trial command and repository.

## Reproduce

```bash
python3 tests/ui_fixture_server.py
# Inspect and operate only the generated temporary fixture, using the dashboard UI.
# Save inventory/plan/complete/restore JPEG screenshots for en and zh-CN into captures/.
node scripts/render_launch.mjs /absolute/node_modules/with/sharp
node scripts/render_walkthrough.mjs /absolute/node_modules/with/sharp
```

Development render tools are optional; running the app and sample trial needs neither Node packages nor ffmpeg. Videos use H.264/yuv420p and MP4 faststart. Public media are draft explanations, not claims that every Mac/drive has been tested.
