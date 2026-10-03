# 按明确清单迁移备份文件

- 状态：本地维护辅助工具，不属于 Runtime Adapter
- 适用版本：当前工作区维护脚本
- 最后验证日期：2026-10-04

`scripts/archive_verified_files.py` 是本地维护辅助工具，只迁移用户明确授权的文件清单。它不是 OpenClaw Runtime Adapter，也不保证归档内容能在任何 Runtime 中恢复或继续工作。

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

示例（先检查不带 `--execute` 的方案，再执行同一明确清单）：

```sh
python3 scripts/archive_verified_files.py \
  --volume '/Volumes/Archive Disk' \
  --volume-uuid '<diskutil 查到的真实 UUID>' \
  --destination '/Volumes/Archive Disk/Memory Harbor/Backups/approved-batch' \
  --source '/absolute/path/approved-backup.tar.gz'
```

回归验证：`python3 -m unittest discover -s tests -v`。测试覆盖完整校验后释放、幂等重试、目标冲突、未获证明的已有链接、损坏副本，以及断盘和链接创建失败时保留原件。
