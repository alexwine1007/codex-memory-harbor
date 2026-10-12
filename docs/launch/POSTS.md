# Launch drafts / 发布文案草稿

**Drafts only. None of these posts or invitations has been sent.** Before publishing, recheck the current version, community rules and the specific account/channel approved by the owner. Disclose that you built/maintain the tool; do not pose as an independent user. One relevant post per community, not mass cross-posting.

## One line / 一句话

**EN:** Codex histories filling your Mac? Dock eligible old logs and cold media on an external drive, verify the copies, and keep original paths readable while connected.

**中文：** Codex 的旧子任务和素材占满了 Mac？安全搬到外盘，外盘在线时仍能沿原路径读取。

## Chinese developer community / 中文开发者社区

**标题：** 做了个开源 Mac 小工具：把 Codex 旧历史和冷素材搬到外盘，保留原路径

长期使用 Codex、子代理和 AI 制作工具，历史和素材会越积越多。直接删掉又怕丢研发证据。我们做了 Memory Harbor（记忆港），想解决这个具体问题。

它只推荐符合条件的已完成子任务和冷素材；你查看清单并确认后，工具复制到外盘、逐个校验，再用链接保留原路径。外盘在线时继续沿原入口读取，想放回本机也有校验后的恢复流程。项目代码、环境和活跃主任务不搬。

目前是 macOS 第三方源码 Beta，MIT 开源，支持中文/英文，不上传历史、不做遥测。没有公开公证安装包，需从源码安装。拔盘时原件不可读；它不是额外备份，也不保证 Codex 自动记住所有旧对话。

想找 5–10 位确实遇到空间问题的朋友，先做只读盘点，再用工具新建的可丢弃样例试一下迁移/读取/恢复。最想听到：哪一步看不懂，恢复是否顺利，安装是不是门槛太高。

仓库和演示：https://github.com/alexwine1007/codex-memory-harbor

安全试用：https://github.com/alexwine1007/codex-memory-harbor/blob/main/docs/launch/TRY.md

我是这个项目的维护者。欢迎反馈具体问题，不需要上传你的私人聊天或日志。

## Show HN — only once it is ready to try

**Title:** Show HN: Memory Harbor – dock old Codex logs on an external drive

I built Memory Harbor for a small Mac SSD and long-running AI work. Instead of deleting completed child-agent logs and cold media, it verifies copies on an external drive and keeps original paths working through symlinks while the drive is connected.

This is a third-party macOS source beta, not an official Codex storage integration. It protects main/active histories, uses fresh volume and file checks, and supports receipt-backed restoration. There is no account, telemetry, cloud upload, or public notarized installer. An external drive is not a second backup, and disconnected originals are unavailable.

You can start with a read-only inventory or a disposable 128 KiB sample trial without putting personal history at risk. The latter runs the production byte core through docking, original-path reads and restore; it does not prove Codex restart/remount behavior on your setup.

I'd especially value feedback about install friction, the first confusing step and recovery on different drive/filesystem combinations. Automatic associative memory and other runtime adapters are not shipped.

Code, demo, and bilingual docs: https://github.com/alexwine1007/codex-memory-harbor

Trial: https://github.com/alexwine1007/codex-memory-harbor/blob/main/docs/launch/TRY.md

## Short introduction / 简短介绍

开源小工具 Memory Harbor：Mac 空间不够时，把合格的 Codex 旧子任务和冷素材校验后放到外盘，外盘在线时保留原路径读取，也可以恢复。macOS 源码 Beta，中文/英文，无遥测。先只读盘点或用临时样例试用，不必先迁移真实历史。维护者正在找实际有这个痛点的内测者： https://github.com/alexwine1007/codex-memory-harbor

## Personal invitation — consent first / 内测邀请

你之前提到 Codex 历史/旧素材占 Mac 空间。我在做一个开源工具 Memory Harbor，想请你帮忙看第一步是否容易理解。先只读扫描，再用工具自己生成的小样例做恢复测试，不需要上传私人记录。你愿意试一下吗？不方便也完全没关系。

## Reply to a relevant report — help first

Do not post an unsolicited advertisement on a bug report. If discussion welcomes external workarounds and the owner's account is approved to reply, first acknowledge the actual OS/runtime and explain the limits. The tool currently supports macOS only; a Windows report is not a matching installation target. Never describe a report as independently reproduced by us.

Public problem reports to review, not marketing targets: [#34061](https://github.com/openai/codex/issues/34061), [#31198](https://github.com/openai/codex/issues/31198), [#35470](https://github.com/openai/codex/issues/35470). Their existence is not a market-size estimate or proof that our tool resolves each underlying bug.
