# DeerFlow 可借鉴能力：补充源码评估

> 评估基线：UniEmployee `0951e32`；本机 DeerFlow `fc9fb2de`；核对日期：2026-09-27。DeerFlow 路径为 `/Users/wrg/mystudy/deer-flow`。本文承接[工具加载机制评估](./deerflow-tool-loading-comparison.md)和[网页抓取/浏览器交付评估](./deerflow-web-crawl-browser-migration.md)，集中讨论除此之外的代码设计。列出源码实现不等于建议照搬，也不代表 DeerFlow 仓库所有配置默认启用。

## 1. 结论

对 UniEmployee 而言，DeerFlow 的可借鉴价值主要在**让外部内容更安全、让 Agent 行动更可核验、让能力变更更可控**，不在继续增加员工工具数量。

需区分 DeerFlow 源码能力与这份本地配置：当前 `config.yaml` 的 `verification.receipts_enabled=true`，receipt 只在委派时显示、judge 关闭；`skill_scan.enabled=true`；`subagent_batches.enabled=false`。远端 ToolResult sanitizer 在本地 lead runtime middleware builder 中默认装配。因而本报告将 receipts/sanitizer/skill scan 记作本地实现且配置可用，将 durable batches 记作代码已存在但当前未启用。

| 次序 | DeerFlow 能力 | UniEmployee 当前状态 | 判断 |
|---|---|---|---|
| **优先评估** | 外部工具结果不可信内容处理 | 有 MCP/网页来源，但编译链中目前能看到权限 Guard，没有统一的远端结果结构性净化 middleware | 先作为网页抓取 P1 的安全前置，并评估现有 MCP 结果；不能把转义当成完整 prompt injection 防护 |
| **P1 条件触发** | 子代理行动凭据与验收核对 | 有工具 Trace、子代理调用和预算控制；Trace 主要回答“发生过什么”，未看到父 Agent 对子 Agent 最终行动断言与调用结果做结构化核验 | 当子代理开始产出报告、调用写工具或需要无人值守交付时有价值；先缩小到高风险/高价值动作 |
| **需求触发** | Skill 包静态扫描与导入审查 | 当前技能来源于项目/配置目录，编译时读入 Store；未见面向任意用户上传 Skill 包的安装管线 | 只有开放外部 Skill 导入或允许技能携带脚本时再投入；不要为了仿插件市场提前做完整扫描产品 |
| **需求触发** | 持久化批量子代理任务 | 已有后台 Agent run、子代理预算；尚未看到独立的持久化批次/逐 item 生命周期 | 仅当一个请求需大量并行、逐项暂停/重试/取消/验收时启动 |
| **需求触发** | 项目级上下文与文档架 | 已有对话、员工/用户隔离记忆、知识库和 artifact；没有 DeerFlow 这种“项目说明 + 项目文档 shelf + 对话成员关系”的一等项目上下文 | 如果出现跨多轮、跨员工的持续项目，再考虑；普通会话记忆和知识库已覆盖当前不少需求 |
| **暂缓** | 通用 Extension 插件市场 | UniEmployee 已有可配置员工/工具/连接器/SOP catalog 与 MCP seam | 只有多个团队需要自行安装/升级第三方扩展，且人工改注册表成为反复成本后才引入 |
| **扩容触发** | 跨实例 Blob Store / 多网关内容寻址 | 当前 artifact 有元数据 ACL、workspace 文件和本地文件快照，部署基线偏单实例 | 只有多个实例共享 artifact、宿主机文件路径导致不可见/备份问题时做；单机加对象存储抽象没有直接用户收益 |

已经在当前方案里做过评估或已有实现的 DeerFlow 类能力，不应再计为新缺口：后台 Agent run/断线重连、任务账本、模型准入/请求超时、子代理预算、工具目录与 Guard、评测用例、员工记忆、SOP/技能运行时读取、图片 artifact 预览。对应状态见[能力验证台账](./deerflow-capability-verification-log.md)。

## 2. 优先评估：外部工具结果的信任处理

### DeerFlow 如何做

DeerFlow 的 `ToolResultSanitizationMiddleware` 对一方 web 搜索/抓取工具按名称处理，对所有带 MCP provenance 的工具按来源处理。它对 ToolMessage 文本中的框架边界/控制标签做结构性 neutralization，并给消息记录 transform 元数据；本地文件/命令工具不处理，避免把正常代码、日志误转义。该 middleware 是在工具返回后、模型再次读入结果前工作的。

这是针对明确威胁面的防御：网页、搜索 snippet、第三方 MCP 服务可以返回攻击者控制的文本；这些文本若伪装框架标记，可能影响模型如何区分可信指令和引用数据。它**不等于语义 prompt injection 检测器**，也不替代用户/员工/工具授权、网络出站控制或人工审批。

### UniEmployee 差距与潜在价值

UniEmployee 通过 `_guard_tool()` 对本地、闭包和 MCP 工具决定执行/拒绝，MCP 工具在 compile 时经 `MultiServerMCPClient.get_tools()` 获取；`Streaming.py` 和 Trace 可记录工具调用结果。但 Guard 解决“当前身份能不能调用工具”，不解决“工具返回的文本该不该被当成指令”。目前 `compiler.py` 传入 `create_deep_agent()` 的 middleware 是文件系统边界和可选子代理预算；repo 未发现统一的远端 ToolMessage 结果净化层。

这项工作会给 `bocha_search`、后续 `web_fetch`、Playwright MCP、CRM MCP 等外部可控内容提供统一处理点。用户收益不是回答一定更聪明，而是缩小“外部页面/MCP 返回伪装系统指令”进入模型上下文的攻击面，并让来源与处理状态可审计。当前连接器已有实际配置，因此适合先做威胁建模和最小验证，不必等到新增网页抓取后才看。

### 建议方案与边界

- 在工具 adapter/装配处保留可信 provenance：`local`、`mcp:<connector>`、`web:<provider>`；不要只用工具名猜来源，也不要相信第三方返回内容自报的来源字段。
- 对远端文本结果统一做大小限制、控制标签 neutralization，并将处理状态记录到 metadata/Trace；保留 tool-call id 和原有错误状态。对于非文本块，不改写图片/二进制数据。
- 先识别 UniEmployee 已有的用户输入安全处理和 middleware 顺序，再决定应在 GuardedTool 外围包装还是 `AgentMiddleware` 接缝处理；成功、拒绝、异常、Command 返回等路径必须一致。
- 安全验收采用定向攻击样例：MCP/web 输出伪造 `<system>`、结束标记、要求泄露环境变量/调用被禁工具等内容；验证它仍只作为引用数据呈现、工具权限仍由服务端策略决定。**标签转义不能作为“已经防住 prompt injection”的结论。**

## 3. P1 条件项：子代理行动凭据和验收核对

### DeerFlow 如何做

DeerFlow 的 `ToolReceiptMiddleware` 在服务端记录工具名、状态、参数摘要、输出摘要、字节数和时间，并在模型上下文预算内提供引用 ID。子代理报告被要求附有可核验的凭据；父侧用调用 ledger 检查引用是否存在、工具名是否锚定正确，未引用或引用错位的行动声明标为未核验。另有 `acceptance_criteria` 结构：委派方给出有限、明确的验收条件，完成后做可机器验证检查（例如文件路径/HTTP 状态/结果存在），再返回子代理状态。

这些凭据证明的是“有一次工具调用并得到某种结果”，**不是证明业务事实正确或目标成功**。DeerFlow 文档和实现也把工具调用凭据与业务验收分开。

### UniEmployee 差距与潜在价值

现有 Trace 已跟踪工具开始/结束和部分状态，SSE 能显示工具状态，子代理预算控制调用量；这些利于调试和成本限制。差异在于，父 Agent 得到的子代理摘要中，尚无一套可依赖的服务端 receipt ledger 与断言核验协议。若子代理只负责辅助搜索，增量价值有限；若它调用 CRM 写接口、生成报告、触发自动化并向用户宣称“已完成”，调用凭据可降低虚报/漏报和人工逐项重查的成本。

### 建议渐进实施

1. 先在 Trace 模型中稳定区分 `tool_call_id / tool_name / status / connector / args_digest / result_digest / timestamp`，不把原始凭据写进模型 prompt。
2. 对需要产物的子代理要求返回 handle（artifact ID、URL、业务记录 ID）和 acceptance criteria；父侧先验证服务器可检查的部分，并把 `verified / unverified / failed` 明确返回用户。
3. 若证据 ID 需出现在模型报告中，必须以服务端签发并保存的 receipt ledger 为准，不能让模型自造 ID；摘要压缩/消息保留变化后仍要验证 ID 指向原始调用。
4. 首期只覆盖一个真实动作（例如 CRM Case 写入后的回读确认或报告 artifact 存在），不改所有员工通用 prompt，不声称语义正确性自动化。

触发条件：P0 试点出现子代理报告无法确认、工具副作用后结果不明确或重复人工验证成本时再进入实施。否则现有 Trace 足够开发阶段定位问题。

## 4. 条件项：Skill 包扫描、批次代理、项目上下文

### Skill 包扫描

DeerFlow 把“技能文档”作为可能含资源/脚本/依赖的包来审查：离线静态规则检查路径穿越、超限、可执行二进制、凭据、危险执行/外传迹象，阻断 CRITICAL 项；读包、确定性 findings、内容 digest 和语义 readiness review 有不同职责。review 目标作为 untrusted data，不会因为被检查就获得工具授权。

UniEmployee 当前把 skill `SKILL.md` 从仓库目录或配置目录读取后写进用户/员工 Store，编译 prompt 确定性提示何时读规程；不是 DeerFlow 的通用第三方 package install 能力。若技能由受信代码库维护，直接引入完整 SkillScan 会增加规则维护负担。若将来支持上传 zip、远程导入或技能 scripts，路径/压缩炸弹/密钥/可执行代码扫描才有明确收益。启动条件是产品开放导入入口，而不是“以后可能会有插件”。

### 持久化批量子代理

DeerFlow 的 batch runtime 把多个独立子任务作为持久化 item 管理，允许查看状态、接受/拒绝、取消/重试，并按并发容量执行；配置可关闭，批次规模也受上限约束。UniEmployee 当前新增的 durable Agent run 解决的是一个会话中一次主 Agent run 断线后继续/回放，不等同于 itemized fan-out batch。子代理 budget 限制次数/并发，也不提供每个 item 的独立恢复面板。

价值仅在“一个用户任务明确拆为许多互不依赖子任务”时成立（批量客户研究、合同检查等）：失败时重跑单项，不重做整批；结果按 item 审核。当前没有业务批任务与并发数据，不建议先建通用 batch 平台。达到触发条件后，先做有上限、只读、可逐项取消/重试的批次，不开放子代理任意写权限。

### 项目级上下文与文档架

DeerFlow Projects 把若干 thread 归到一个长期项目，向 run 注入被服务端固定的 project id/name/instructions 和有界文档索引；文档以内容 hash 和独立 ID 存储、immutable，并按项目权限管理。文档上下文是请求级、标注 provenance 的注入，不混进持久对话 transcript。这个设计适合长期研究/交付项目，可避免把一份大资料复制进每次聊天。

UniEmployee 已有用户/员工隔离记忆、知识库、对话和 artifact/部门共享。项目级上下文会新增成员关系、项目访问控制、文档 pin/version、跨会话上下文、归档/删除规则等业务概念。只有同一工作项目需要跨聊天、跨员工共享文件与指令时，它才比知识库或共享 artifact 更有价值。

## 5. 暂缓项及理由

- **Extension 插件市场**：DeerFlow 管理 extension package、entry point、设置、启停、升级和依赖锁定，并做 schema/namespace/执行保护。这是成熟扩展宿主的产品投入。UniEmployee 的员工 catalog、工具授权和 MCP 已提供当前接入 seam；若还没有外部开发者和频繁重复集成，扩展市场只会增加安装依赖、权限审查和升级责任。
- **通用 goal loop / 自动续跑**：总体迭代方案已列为暂缓。当前有后台 run、断线重连、状态恢复范围；自动目标判定会产生额外模型调用和无进展续跑。先从实际 run trace 统计“用户重复说继续”和上下文失效，不再另起平行框架。
- **多 provider 全量搬迁**：DeerFlow 有 Jina、Crawl4AI、Browserless、Firecrawl、Exa 等适配。provider 数量本身不会提升正确性；多个 provider 增加密钥、费用、故障路由、SSRF 边界和排障成本。先证明当前搜索/正文抽取存在覆盖缺口，再针对一种 provider 做试点。
- **对象存储/Blob Store 抽象**：DeerFlow 内容寻址 BlobStore 能让 checkpoint 引用跨机器有效，且以 SHA-256 校验。UniEmployee 现有 artifact 有 ACL，且当前按单节点 Docker 部署/恢复验证；在扩容前增加对象存储抽象会扩大实现面。多实例正式目标或本地 artifact 备份不一致时再启动迁移评估。

## 6. 评审用优先级和可量化收益

| 优先级 | 可借鉴项 | 解决的具体不足 | 做完以后用户能得到什么 | 先收集的证据 |
|---|---|---|---|---|
| **P0 评估** | 外部工具输出净化/来源标记 | Guard 控制谁可调用，但远端返回文本如何作为不可信证据进入模型尚无统一处理 seam | 缩小外部内容伪造框架结构标记、混淆指令/资料的风险；让审计知道内容来自哪类 connector | 现有 MCP/web 工具名和来源清单；恶意 tool result 路径；当前输入净化 middleware 是否覆盖 MCP 输出 |
| **P1 有条件** | 可核验子代理行动 receipt + acceptance criteria | Trace 可观察调用，但子代理摘要没有统一、服务端可核对的行动证据合同 | 对“Case 已创建/文件已生成/操作已完成”提供明确的成功、失败或待核验状态，减少人工复查 | 真实失败/虚报样例、子代理结果不确定案例、写工具的回读现状 |
| **P1 有条件** | 轻量 Skill 导入审查 | 当前流程信任由受控目录/管理员维护的技能文档 | 开放导入后可在激活前拒绝危险文件、秘密和高风险脚本，降低供应链风险 | 是否开放自助上传、技能是否含脚本、技能版本来源与谁可启用 |
| **P2 有条件** | 子代理持久化批次 | 不支持逐项跟踪/恢复大量独立子任务 | 只重试失败 item、查看分项进度，降低整批重跑时间和费用 | 单次调用的独立子任务数、失败率、整批重跑成本、人工核验时间 |
| **P2 有条件** | 项目文档 shelf | 没有 project entity 来组织多会话多员工持续工作 | 同项目共享稳定指令和文件，同时保持每次 run 上下文有界 | 跨会话协作次数、重复上传次数、现有 knowledge base/artifact 无法表达的具体样本 |
| **暂缓/扩容** | 插件宿主、BlobStore、多 provider | 现阶段缺少需自助安装第三方扩展/多副本文件共享/provider 故障切换的证据 | 规模达到目标后降低集成或扩容成本 | 自助集成需求、跨实例读不到 artifact、单 provider 可用性/费用基线 |

注意：P0 表示先评估现实攻击面，不等于本轮已确认出现漏洞；P1/P2 表示需要具体失败样本后再排开发。验收同时看价值指标和安全回归，不能以“middleware 加上了”作为收益。

## 7. 架构迁移建议

这些设计与 LangChain/LangGraph 接口兼容，但最适合在 UniEmployee 的**模块接缝**落地，而不是移植 DeerFlow harness：

- 外部结果处理与 receipt 都发生在工具调用结果与 Agent 下一次模型调用之间，可用当前 `create_deep_agent(middleware=...)` 接口承载；小接口负责来源识别、消息变换/记录，复杂协议留在 middleware 内部。测试通过同一接口注入本地/MCP fake tool，避免连真实外部系统。
- acceptance criteria / 子代理批次属于当前 subagent adapter 与后台 Agent run 之间，需要明确主 run、child execution、item 的取消/存储关系。不要把长任务数据库表和 LangGraph checkpoint 混成同一状态源。
- Skill scan 应当是导入/升级时的独立、离线审查 Module，运行时 Agent 只看到已批准的不可变版本/摘要；不要在每次 compile 时扫描网络或执行包内脚本。
- Project 文档和 BlobStore 都属于数据/Artifact seams；做之前先确认现有 ACL、tenant isolation、备份恢复路径可以用适配器满足，避免同时改变存储布局和 Agent prompt。

因此：**LangChain 帮助的是工具/中间件调用接口的复用；跨进程生命周期、数据库模型、租户授权与用户体验仍需要 UniEmployee 自己的适配。**

## 8. 源码依据

UniEmployee：

- [`compiler.py`](../../backend/app/compiler.py)：工具装配、Guard 替身、MCP discovery、当前 middleware 注册。
- [`streaming.py`](../../backend/app/streaming.py)、[`traces.py`](../../backend/app/traces.py)：工具事件流与 Trace callback。
- [`artifact_storage.py`](../../backend/app/artifact_storage.py)、[`routes/workspace.py`](../../backend/app/routes/workspace.py)、[`conversations.py`](../../backend/app/conversations.py)：artifact 内容落盘、ACL 与工作区访问。
- [`catalog/resources.py`](../../backend/app/catalog/resources.py)、[`catalog/employees.py`](../../backend/app/catalog/employees.py)：Skill 目录/员工绑定来源。
- [总体迭代决策方案](./deerflow-value-driven-iteration-plan.md)、[能力验证台账](./deerflow-capability-verification-log.md)：本项目已有建设及验证状态。

DeerFlow（本机 `fc9fb2de`）：

- [`tool_result_sanitization_middleware.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/agents/middlewares/tool_result_sanitization_middleware.py:1>)、[`tool_error_handling_middleware.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py:210>)：远端结果净化与 middleware 装配。
- [`tool_receipt.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/agents/middlewares/tool_receipt.py:1>)、[`tool_receipt_middleware.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/agents/middlewares/tool_receipt_middleware.py:45>)、[`receipt_verification.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/agents/middlewares/receipt_verification.py:1>)：工具调用 receipt 与引用核验。
- [`report_contract.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/subagents/report_contract.py:1>)、[`task_tool.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/tools/builtins/task_tool.py:1089>)：子代理报告/验收协议。
- [`skillscan/orchestrator.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/skills/skillscan/orchestrator.py:1>)、[`skills/review/analyzer.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/skills/review/analyzer.py:1>)：离线 skill 安全扫描和只读包审查。
- [`subagents/capacity.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/subagents/capacity.py:1>)、[`subagent_batches`](</Users/wrg/mystudy/deer-flow/config.yaml:1975>)：子代理并发容量；持久化 batch 默认关闭且有规模上限。
- [`projects/context.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/projects/context.py:1>)、[`projects/documents.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/projects/documents.py:1>)：项目上下文与项目文件 shelf。
- [`storage/contract.py`](</Users/wrg/mystudy/deer-flow/backend/packages/harness/deerflow/storage/contract.py:1>)：SHA-256 内容寻址 BlobStore contract。
