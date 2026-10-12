# Try Memory Harbor safely / 安全试用

English instructions and Chinese notes share the same commands. macOS 13+, Python 3.9+, Git. No third-party Python packages are required. An app build additionally needs Apple's Command Line Tools; no public notarized Mac installer is included in this beta.

## 1. Read-only inventory

```bash
git clone https://github.com/alexwine1007/codex-memory-harbor.git memory-harbor
cd memory-harbor
python3 skills/codex-memory-harbor/scripts/harbor.py scan
```

This scans metadata and updates Memory Harbor's own local index. It does not migrate files, change Codex's database or upload history. “Read-only” here concerns your source files; it is not a promise that no cache is written. / 只读指不修改你的来源文件；会维护记忆港自己的本机索引。

To inspect the real UI locally:

```bash
python3 skills/codex-memory-harbor/scripts/harbor.py serve --port 0 --open
```

Reviewing or cancelling a plan does not move files. The service binds to `127.0.0.1`; close the terminal with Ctrl-C when finished. Do not confirm a real batch until you understand its source list and destination. / 看方案和取消确认不会移动文件；首次操作真实内容前请核对清单。

## 2. Disposable byte-transaction trial

First see a plan. This command does not read your Codex home or create samples:

```bash
python3 scripts/try_harbor.py
```

Then connect a drive and replace the placeholder with its **exact mounted name**:

```bash
python3 scripts/try_harbor.py --volume "/Volumes/Your SSD" --execute
```

`--execute` authorizes only the **new 128 KiB sample** created by this script. No user-provided source paths or private history are accepted. It uses the production byte-transaction core: copy, fsync, SHA-256 readback, original-path symlink, retained local rollback, independent original-path read, then restoration. Every volume check uses the real mounted-volume UUID; no security check is mocked in this trial.

这一步只操作工具自己新建的 128 KiB 文本样例，不读取或迁移你的 Codex 记录。它保留本地回滚，再沿原路径读取，最后恢复到本机，不是在帮你清理真实空间。

Success prints `"status": "passed"` and ends with `restored_and_both_copies_verified`. Local sample, external sample, and receipts are retained for inspection. Only remove the printed **Memory Harbor Trial** / **memory-harbor-trial-** sample directories after inspecting them. The script offers no automated deletion. If it stops, preserve the directories and report the step/error class, not private logs.

This verifies the **byte layer on your selected drive**, not Codex restart/resume, physical unplug/remount, editor hot reload, all filesystem metadata or power-loss recovery. 不把样例通过当成整个生产项目已经验证。

## 3. First real batch — you control it

- Install from source via `./scripts/install_macos.sh` if desired; do not disable Gatekeeper.
- Start small, on non-critical completed child histories or eligible cold media; star anything that must stay local.
- Review the exact plan and **keep local copies** on a new machine/drive until its recovery checks are accepted.
- Independently verify original-path reads, restore, then Codex restart/remount as applicable. Do not physically yank a drive during a write.
- Only after successful checks, explicitly authorize local-copy release. Copying with local retention is not a space-release claim.
- An external drive is not a second backup. Keep a separate backup for irreplaceable work.

外盘在线时原路径能读取；拔盘后原件暂时不可读。小索引能查到已索引的信息，不代表全文离线可读，也不代表新任务自动联想到所有旧内容。

## 4. Give useful, private-safe feedback

Open [Beta trial feedback](https://github.com/alexwine1007/codex-memory-harbor/issues/new?template=beta_feedback.yml). Tell us whether you completed scan, disposable trial, restore and a voluntary week of use. These are separate outcomes. Share version, macOS version, filesystem, medium type and the first confusing step; anonymize paths. Never paste session JSONL, keys, tokens, private images or signing material. For sensitive vulnerabilities use [SECURITY.md](../../SECURITY.md).
