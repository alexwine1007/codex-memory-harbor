# 按明确清单迁移备份文件

- 状态：本地维护辅助工具，不属于 Runtime Adapter
- 适用版本：当前工作区维护脚本
- 最后验证日期：2026-10-04

`scripts/archive_verified_files.py` 是本地维护辅助工具，只迁移用户明确授权的文件清单。它不是 OpenClaw Runtime Adapter，也不保证归档内容能在任何 Runtime 中恢复或继续工作。

0.4.5 beta 保留该命令入口，实现位于随 Skill 安装的 `scripts/archive_files.py`，由维护命令和项目停泊接口共用。项目相对路径清单、默认本地副本、释放与恢复合同见[项目文件停泊](../../skills/codex-memory-harbor/references/project-storage.md)。

安全顺序：检查外置卷 UUID 和文件句柄 → 流式复制并计算源 SHA-256 → 回读外盘校验大小与 SHA-256 → 临时保留本地回滚文件 → 建立原路径的绝对符号链接 → 分别复核链接内容和回滚文件 → 持久化校验记录 → 释放本地实体。

- 默认只展示方案；执行必须显式传入 `--execute`。
- 来源文件不解压、不改写、不上传；凭据和备份内容不进入记录。
- 校验记录在目标目录的 `archive-receipt.jsonl`，包含原路径、目标路径、长度、哈希和状态。
- 目标文件名重复、已有目标冲突、来源变化、句柄检查失败或卷身份变化时立即停止。
- 一次文件失败即停止批次；此前已完成的文件不重复迁移。
- 已迁移链接只有匹配此前记录及完整哈希才被视为成功重试。
- 失败可能留下外盘上的不完整副本，不自动覆盖或删除；本地原件或回滚文件始终保留。
- 外盘必须保持挂载；断开时原路径链接不可读。本工具不提供离线缓存或原生 Runtime 连续性。
- 此工具不进行 Git 临时文件清理。该类删除必须另行取证并取得用户确认。
- 多文件批次可通过 `--source-plan` 使用用户确认的冻结 JSON 清单，替代重复的 `--source`。执行前及每个文件复制前检查长度、修改时间和 inode；不在执行过程中重新展开通配符或加入新文件。清单至少含 `count`、`total_bytes` 和 `files`，每行文件记录含 `source`、`bytes`、`mtime_ns`、`inode`。
- 要保留具有研究或审计价值的 Git 临时残片时，同样按完整字节归档，而不是修复或提取其中的 Git 对象。归档说明必须区分完整研究原件与不完整残片，并在原项目提供查找入口；不得把残片称作可恢复的完整 Git 历史。

示例（先检查不带 `--execute` 的方案，再执行同一明确清单）：

```sh
python3 scripts/archive_verified_files.py \
  --volume '/Volumes/Archive Disk' \
  --volume-uuid '<diskutil 查到的真实 UUID>' \
  --destination '/Volumes/Archive Disk/Memory Harbor/Backups/approved-batch' \
  --source '/absolute/path/approved-backup.tar.gz'
```

回归验证：`python3 -m unittest discover -s tests -v`。测试覆盖完整校验后释放、幂等重试、目标冲突、未获证明的已有链接、损坏副本，以及断盘和链接创建失败时保留原件。
