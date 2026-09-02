# Memory Harbor

Memory Harbor 保存个人与智能代理共同完成的工作历史，使其在离开活跃存储后仍然可验证、可发现、可访问，并在运行时能力允许时可继续。

## Language

**Agent Runtime**:
承载 Agent 工作、保存其原生历史身份并决定历史如何打开或继续的运行环境。Claude Code、Codex 和 OpenClaw 是候选 Agent Runtime。
_Avoid_: Model, provider

**Harness**:
围绕一个或多个模型提供任务编排、工具调用、状态保存和交互入口的 Agent Runtime 形态。
_Avoid_: Model

**Model Provider**:
提供推理模型或模型接口但不必拥有任务历史合同的系统。DeepSeek 通常属于这一类，除非所指的是一个具体的持久化客户端或 Harness。
_Avoid_: Runtime, Harness

**History Object**:
某个 Agent Runtime 中可被独立识别、保护、停泊、校验和恢复的最小工作历史实体。
_Avoid_: File, chat log

**Docking**:
历史对象在保留可验证证据和已声明连续性能力的前提下，从活跃存储迁入冷存储的状态转换。
_Avoid_: Cleanup, deletion, backup

**Native Continuity**:
历史对象停泊后，原 Agent Runtime 仍能按其原生身份发现和使用该对象的能力总称；具体能力必须声明为可发现、证据可读、原生可打开或可继续工作。
_Avoid_: Backup success, file exists

**Runtime Adapter**:
一个 Agent Runtime 的原生历史合同与 Memory Harbor 历史对象合同之间的翻译者。
_Avoid_: Importer, one-off script

**Storage Adapter**:
某类存储后端与 Memory Harbor 的可用性、持久化、完整性、物化和恢复合同之间的翻译者。
_Avoid_: Destination path

**Recall Lead**:
从本地索引返回、带有原始出处但尚未被提升为当前事实的有限历史线索。
_Avoid_: Memory, instruction, truth

**Evidence Receipt**:
记录一次停泊、校验、恢复或兼容性验收所使用对象、阶段结果、时间、版本和完整性标识的可审计证明。
_Avoid_: Success message, log line
