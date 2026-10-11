# 桌面端与仪表盘

- 状态：当前实现，包含已记录的设计债务
- 适用版本：Memory Harbor 0.4.5-beta.1（macOS）
- 最后验证：2026-10-12

## 用途

桌面层常驻一个低成本状态卡，把功能更完整的仪表盘及其 Python 进程隔离到按需启动的辅助应用中。本章只描述已经存在的实现；目标体验另见[前端设计基础](../design/FRONTEND_FOUNDATION.md)。

## 进程拓扑

```text
Memory Harbor 紧凑状态卡（原生 Cocoa，辅助应用）
    │ 用户打开港口
    ▼
Memory Harbor 仪表盘辅助应用（原生 Cocoa，普通应用）
    │ 启动并持有
    ▼
harbor.py 本机回环服务（127.0.0.1，随机可用端口）
    │ 提供页面与接口
    ▼
WKWebView 中的静态 HTML / CSS / JavaScript
```

仪表盘打开时，紧凑状态卡的拥有者进程继续存活，但隐藏窗口。返回桌面后，仪表盘辅助应用退出；由它持有的服务监视父进程并随之退出。紧凑卡随后恢复原来的桌面位置并刷新摘要。

辅助应用使用随机可用的本机回环端口，接口不依赖固定端口。服务通过标准输出把实际 URL 交给辅助应用；辅助应用确认服务就绪后才显示 WebKit 页面。

## 源码地图

| 文件 | 职责 |
| --- | --- |
| `macos/CodexMemoryHarbor.swift` | 紧凑窗口、挂载与唤醒事件、状态进程、辅助应用生命周期 |
| `macos/CodexMemoryHarborDashboard.swift` | 仪表盘窗口、服务所有权、WKWebView、Codex 深链接 |
| `skills/codex-memory-harbor/scripts/harbor.py` | 扫描、目录、召回、状态变更接口与本地服务 |
| `skills/codex-memory-harbor/assets/dashboard/index.html` | 当前仪表盘文档结构 |
| `skills/codex-memory-harbor/assets/dashboard/styles.css` | 当前仪表盘样式 |
| `skills/codex-memory-harbor/assets/dashboard/app.js` | 当前仪表盘状态、渲染与操作 |
| `scripts/build_macos_app.sh` | 主应用与辅助应用打包、资源、属性表和签名 |
| `scripts/install_macos.sh` | 正式安装、旧身份退役、Skill 同步与登录启动 |

## 当前紧凑状态卡合同

原生状态卡调用 `compact-status`，只接收空闲界面需要的摘要值，不接收任务清单或召回片段。挂载、卸载、卷重命名和系统唤醒会触发有界刷新；空闲状态没有周期轮询。

当前首要信息已经从“能释放多少空间”改为“已停泊历史有多少当前可访问”：

- 主数值：`当前可访问数 / 已停泊总数`；
- 状态：记忆都在、有些记忆暂时离线或暂时看不清状态；
- 次要提示：可安全停泊的历史数量与容量；
- 存储设备名称、可用容量与连接状态；
- “打开港口”进入隔离的仪表盘辅助应用。

紧凑状态接口不执行停泊、释放或恢复，也不会读取历史正文。

## 当前仪表盘传输边界

服务只绑定 `127.0.0.1`。`/api/config` 返回当前进程专用的操作令牌，所有会改变状态的请求必须携带该令牌。仪表盘不读取浏览器凭据，当前前台路径不发起外部网络请求。

读取接口：

- `GET /api/config`
- `GET /api/scan`
- `GET /api/volumes`
- `GET /api/storage-targets`
- `GET /api/catalog`
- `GET /api/search`
- `GET /api/recall`

操作接口：

- `POST /api/settings`
- `POST /api/protect`
- `POST /api/task-detail`
- `POST /api/task-record`
- `POST /api/rebuild-catalog`
- `POST /api/repair-links`
- `POST /api/build-recall-index`
- `POST /api/plan`
- `POST /api/offload`
- `POST /api/migrate`
- `POST /api/audit`
- `POST /api/finalize`
- `POST /api/restore`
- `POST /api/project-plan`（按需盘点、生成卷身份绑定的冻结文件方案）
- `POST /api/project-file-offload`（执行明确选中的单个素材，默认保留本地副本）
- `POST /api/project-file-restore`（按原始回执恢复单个素材）

项目盘点不加入普通历史扫描；候选素材与历史容量分别显示。素材列表按目录分组、每页 100 项，全选覆盖完整冻结方案。项目方案详情与恢复边界见[项目存储](../../skills/codex-memory-harbor/references/project-storage.md)。

部分 POST 接口本质上偏读取，但仍要求操作令牌。HTTP 方法不是安全等级，底层操作合同才是判断依据。

## 当前前端状态

`app.js` 目前持有一个全局快照，以及选择、推荐、保护、展开、搜索、筛选、排序和活跃任务等状态。它通过 HTML 字符串渲染，并在每次渲染后重新绑定事件。这对 beta 阶段足够，但界面层仍然偏浅：传输、数据归一化、策略说明、渲染和操作编排耦合在一起。

后续改版应按“前端设计基础”中的模块切分，在不顺带改变后端安全合同的前提下加深界面结构。`docs/design/prototype/` 当前只是静态中文交互样板，不连接 `/api`，也不会触发真实历史操作。

## 当前生命周期与失败行为

- 本地服务响应前，辅助应用隐藏 WebKit。
- 启动失败会关闭空窗口、显示中文原因并退出辅助应用。
- 服务意外退出时关闭辅助应用，不留下冻结仪表盘。
- 服务监视辅助应用 PID，并在所有者退出后停止。
- 安装脚本会清理由旧版本精确路径留下的孤儿进程。
- 紧凑状态卡使用辅助应用激活策略，不常驻 Dock。
- 只有单独签名的仪表盘辅助应用在打开时显示于 Dock。

这些结论由当前测试和带日期的证据账本支撑，不自动外推到其他 Mac、文件系统或 Runtime Adapter。

## 当前设计债务

- 仪表盘的导航、术语和数据假设仍偏 Codex；
- 所有作业仍集中在单页和单个全局 JavaScript 状态对象中；
- Cocoa 与 CSS 之间存在重复样式值；
- 视觉语义尚未沉淀为共享 token；
- 部分控件仍依赖过小的元信息文字或文字符号；
- 响应式 CSS 仍按子元素位置隐藏列；
- 前端验证仍以静态字符串与后端流程测试为主；
- 尚无覆盖空状态、健康、离线、权限、完整性失败和部分失败的截图基线；
- Skill 内仍有旧版 widget 资源，需要在正式改版前决定保留或退役。

## 安全人工检查

1. 打开已安装的 `Memory Harbor.app`，确认紧凑状态卡出现，且没有常驻辅助应用或 Python 服务。
2. 点击“打开港口”，确认一个辅助应用只持有一个随机端口的本机回环服务。
3. 将界面摘要与 `harbor.py compact-status`、`harbor.py scan` 的结果对照。
4. 使用样例状态检查健康、空状态和离线界面，不调用任何变更接口。
5. 返回桌面，确认辅助应用和服务退出，而紧凑状态卡继续存在。

真实停泊、释放、恢复、拔盘和权限拒绝属于独立验收流程。不要为了检查版式而操作真实历史。
