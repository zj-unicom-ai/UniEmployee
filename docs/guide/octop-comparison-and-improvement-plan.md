# Octop 深入研究与 UniEmployee 完善建议

研究日期：2026-10-19。研究对象是用户提供的两个本地仓库，结论以源码为准。

- Octop：`/Users/wrg/mystudy/Octop`，提交 `dd9dce47`，本地版本 `1.0.2`。
- UniEmployee：`/Users/wrg/Important/UniEmployee`，提交 `c38a00a`，本地版本 `0.21.6`。
- 方法：沿运行入口、Agent 装配、权限上下文、知识检索、外部集成、执行记录、评测、产物和 CI 核查实现，并交叉检查文档。未读取业务密钥、未启动生产服务、未执行真实业务操作。
- 本文是静态实现评估，不是压测、安全渗透或客户环境验收。下文明确区分代码行为、风险推断和建议目标。检查了 [Octop 官方仓库](https://github.com/TencentCloud/Octop) 的定位；功能判断固定在上述本地提交，不把线上后续变化算入本次基线。

## 1. 核心判断

**UniEmployee 应借鉴 Octop 的集成和使用体验，继续深化企业业务执行与治理。当前最有价值的工作，是让已有员工能在真实权限下完成真实任务，并提供可验证的结果。**

Octop 的主线是“自托管助手产品”：多入口、个人授权连接器、专家与团队、工作区、记忆、浏览器和终端。UniEmployee 的主线是“企业岗位平台”：配置员工、绑定技能与业务资源、按流程执行、审批、业务本体、数据分析、交付产物和审计。两者有大量共同基础，但优先解决的问题不同。

不能把 Octop 的界面数量当作企业成熟度，也不能因 UniEmployee 使用 PostgreSQL、审批和 Trace 就认为真实业务闭环已经完成。代码中最需要优先完善的四处边界是：

1. 员工知识库映射为空时，会扩大到全局知识集范围。
2. 工单、退款示例工具会返回成功信息，却没有真实业务写入。
3. 连接器凭据可能随完整配置进入响应和审计快照。
4. 外部 IM 还是通用 webhook，授权、身份核验和投递可靠性尚需补齐。

这些优先于再增加一批员工、切换前端框架或建设通用插件市场。

## 2. Octop 的架构与值得借鉴之处

### 2.1 控制面与执行能力分层

Octop 的 Python 包包含 FastAPI API、Click CLI 和构建后的 React 控制台；领域逻辑位于 `infra/`，HTTP/CLI 调用领域服务，数据库访问主要通过 `RepoBundle/SharedServices` 装配。运行时由多个独立组件组合：

| 组件 | 本仓负责的部分 | 需要明确的依赖边界 |
|---|---|---|
| Agent 生命周期 | 配置、用户归属、启动/停止、热更新、团队装配 | Agent 执行、部分工具与上下文管理依赖 `octop-harness` |
| IM | 频道管理、路由、会话、消息投影和回应模式 | 平台适配驱动主要依赖 `octop-gateway` |
| 记忆 | 配置、管理 API、审阅界面、迁移与维护协调 | 提取和存储引擎依赖 `octop-memory` |
| 浏览器 | 控制台、HTTP/WS 接入、录制回放接口 | 浏览器会话与执行依赖 `octop-browser` 等组件 |
| ACP | 用户 runner 配置、授权、装配和 CLI 入口 | 协议运行依赖 harness |

源码依据：[依赖与打包](/Users/wrg/mystudy/Octop/pyproject.toml:15)、[团队桥接](/Users/wrg/mystudy/Octop/src/octop/infra/agents/teams/team_manager.py:24)、[网关装配](/Users/wrg/mystudy/Octop/src/octop/infra/gateway/gateway.py:251)。这意味着可以借鉴它的模块边界；直接移植 UI 或替换一个 Python 包，并不会自动得到整套能力。

### 2.2 连接器是用户授权实例

Octop 不只保存 MCP command/URL，还在 connection 上记录用户、共享属性、凭据、有效期和轮转信息。它实现了 OAuth PKCE、一次性 state、token 交换/刷新、凭据加密和运行时重新装配。这个设计适合“同一个员工替不同用户查不同系统”。

源码依据：[连接器记录](/Users/wrg/mystudy/Octop/src/octop/infra/db/repos/connectors.py:13)、[连接服务](/Users/wrg/mystudy/Octop/src/octop/infra/connectors/service.py:114)、[PKCE](/Users/wrg/mystudy/Octop/src/octop/infra/connectors/oauth/pkce.py:17)、[OAuth 回调](/Users/wrg/mystudy/Octop/src/octop/api/routers/connectors.py:1465)。

它也不是完整的密钥托管范本：Fernet 主密钥存于同一控制数据库，数据库整体泄露时，加密不能形成独立防护边界。参考其用户连接模型时，UniEmployee 应采用独立环境密钥或企业密钥服务，并建立轮转机制。见 [凭据加密](/Users/wrg/mystudy/Octop/src/octop/infra/connectors/crypto.py:15)、[密钥表](/Users/wrg/mystudy/Octop/src/octop/infra/db/repos/secrets.py:15)。

### 2.3 记忆成为用户可管理的数据

Octop 提供 atoms、原始事件、实体、episodes、候选记忆、journal 等管理接口，支持候选提升/拒绝、记忆废弃/替换、提取参数设置；还有存储维护和迁移界面。它把“记住了什么”变成可以检查和纠正的产品能力。

源码依据：[记忆查询](/Users/wrg/mystudy/Octop/src/octop/api/routers/memory.py:309)、[候选审阅与废弃](/Users/wrg/mystudy/Octop/src/octop/api/routers/memory.py:637)、[后端选择](/Users/wrg/mystudy/Octop/src/octop/infra/agents/memory/backend.py:14)。本次确认了接口与装配存在，没有独立验证外部记忆引擎的提取质量。

### 2.4 独立专家组成团队

Octop 团队有主持人和独立成员。主持人只负责派工与汇总，成员保留自己的工作区与会话，团队时间线标识说话人；成员执行中的审批也有协调逻辑。相比把子代理当作一次工具调用，这更接近用户理解的“几位员工一起干活”。

源码依据：[主持人工具白名单](/Users/wrg/mystudy/Octop/src/octop/infra/agents/teams/service.py:28)、[房间与成员执行](/Users/wrg/mystudy/Octop/src/octop/infra/agents/teams/team_manager.py:133)。

但团队仍是 Beta：在途任务锁是内存记录，重启会消失；文档也明确后台 inbox 没有进程外持久化。停止主持人不等于停止所有成员。**适合学习协作界面和权限收敛，不适合直接照搬为可靠业务编排。**见 [在途任务追踪](/Users/wrg/mystudy/Octop/src/octop/infra/agents/teams/jobs.py:8)、[团队限制](/Users/wrg/mystudy/Octop/docs/expert-teams.md)。

### 2.5 模型健康路由比静态默认模型更完整

Octop 的 AUTO 模式在模型调用中间件层处理重试和切换：区分模型故障与供应商故障，记录熔断状态，限制半开探测，并检查备选模型的上下文容量和多模态需求。显式指定模型不会一律被自动替换。

源码依据：[故障分类与熔断](/Users/wrg/mystudy/Octop/src/octop/infra/agents/providers/health.py:60)、[安全切换中间件](/Users/wrg/mystudy/Octop/src/octop/infra/agents/middleware/model_failover.py:59)。这比收到错误后重新执行整条 Agent 流程更值得借鉴：后者可能重复业务副作用。

### 2.6 专家发布与安装形成资产复用链路

Octop 支持专家发布快照、刷新、下架、安装，导出时排除部分会话、上传、日志和凭据文件；插件支持 manifest、启停和能力注册。适合借鉴的是“员工能力包”，让配置可以检查依赖、安装、升级和回滚。

源码依据：[专家发布安装](/Users/wrg/mystudy/Octop/src/octop/infra/agents/experts/published_creation.py:180)、[快照导出](/Users/wrg/mystudy/Octop/src/octop/infra/agents/experts/publish.py:136)、[插件管理](/Users/wrg/mystudy/Octop/src/octop/infra/agents/plugins/manager.py:293)。插件市场当前仍有仓内 catalog 实现，不能等同已验证的远程可信市场；按文件名排除密钥也不能代替完整的秘密扫描。

## 3. 双方能力对比

下表比较的是源码覆盖范围，不是性能或质量评分。

| 维度 | Octop 本地实现 | UniEmployee 当前实现 | 对 UniEmployee 的判断 |
|---|---|---|---|
| 定位 | 个人、家庭、小团队自托管助手 | 企业数字员工与岗位业务 | 保持企业主线 |
| 员工配置 | 专家库、用户实例、团队、共享安装 | catalog 配置、个人有效配置、资源指派 | 已有基础，补发布与版本治理 |
| 多 Agent | 独立专家互调、异步团队房间 | deepagents 子代理、路由策略、调用预算 | 补跨员工协作产品层，按场景推进 |
| SOP 与业务约束 | 技能与专家配置 | 技能、SOP、退款 StateGraph、人工审批 | 保留确定性流程优势，接真实业务 |
| 企业数据 | 文档知识库、外部连接器 | RAGFlow、业务本体、SQL 分析工作台 | 深化数据权限和证据链 |
| IM | 网关统一接入，多平台依赖适配器 | Web 频道与通用入站/出站 webhook | 优先接通一个真实企业 IM |
| 外部授权 | 用户 connection、OAuth、凭据生命周期 | 全局 connector 配置及员工授权 | 从资源配置升级为授权实例 |
| 记忆 | 提取、候选、审阅、维护、迁移接口 | 用户×员工隔离 Store，自动加载记忆文件 | 补用户可治理性 |
| 工作区 | 多存储后端与文件操作界面 | 会话产物快照、预览、个人归档、部门 ACL | 在现有产物中心上完善验收和来源 |
| 浏览器/终端 | 可视浏览器、PTY、远程操作、ACP | Playwright MCP、执行工具、OpenSandbox | 按业务补可见与接管，不必补齐所有入口 |
| 模型可靠性 | AUTO 故障分类、重试、健康切换 | 模型目录、超时、并发准入与排队 | 补模型健康与策略路由 |
| 运行可靠性 | 单进程，历史投影，团队有内存边界 | 后台 run、SSE 重放、自动化账本/CAS/心跳 | 已有基础，补接续和跨实例一致性 |
| 测试工程 | Ruff、mypy、pytest、前端 TS/Vitest、跨平台 CI | SQLite pytest、PG 集成 CI、Vite build | 渐进加入静态检查与关键用户流测试 |
| 企业质量运营 | 有历史、usage、基础指标 | Trace、反馈、真实员工基准运行及人工评分 | 做成发布质量门槛和费用治理 |

UniEmployee 对照依据：[编译器](/Users/wrg/Important/UniEmployee/backend/app/compiler.py:623)、[分析工作台](/Users/wrg/Important/UniEmployee/backend/app/agent/analyst/datasource/manager.py)、[运行记录](/Users/wrg/Important/UniEmployee/backend/app/agent_runs.py:1)、[评测运行](/Users/wrg/Important/UniEmployee/backend/app/routes/admin.py:714)、[工作区](/Users/wrg/Important/UniEmployee/backend/app/routes/workspace.py:72)、[CI](/Users/wrg/Important/UniEmployee/.github/workflows/ci.yml)。

## 4. 必须纠正的现状认知

UniEmployee 的 `AGENTS.md` 和旧企业路线图部分内容已经落后，不能直接拿来作为差距清单：

| 旧判断 | 当前源码显示 |
|---|---|
| 没有 PostgreSQL CI | CI 已有 PostgreSQL 16 服务与专用集成测试 |
| 备份不包含工作区文件 | 已有 7 库加 workspace 联合备份及隔离恢复验证脚本 |
| 资源中心改配置必须重启 | 多个管理变更已调用本进程 `runtime.invalidate`；技能正文也有同步机制 |
| 新员工只靠空库 seed | 启动路径已有员工、技能、工具等多种 backfill，具体效果需逐项检查 |
| 对话任务只随 SSE 连接存活 | 已有独立后台任务和持久 SSE 事件，能重连重放 |
| 没有评测与负载保护 | 已有评测集、批量运行、人工评分、模型准入、子代理预算 |
| 生产默认加载所有演示资产 | 已有生产预检和演示资产阻断，但本地模拟业务工具仍需补管 |

依据：[启动装配](/Users/wrg/Important/UniEmployee/backend/app/main.py:40)、[配置失效](/Users/wrg/Important/UniEmployee/backend/app/runtime.py:102)、[连接器热失效](/Users/wrg/Important/UniEmployee/backend/app/routes/admin.py:377)、[备份](/Users/wrg/Important/UniEmployee/scripts/backup.sh:1)、[恢复验证脚本](/Users/wrg/Important/UniEmployee/scripts/verify_backup_restore.py:23)、[模型准入](/Users/wrg/Important/UniEmployee/backend/app/model_admission.py:1)、[子代理预算](/Users/wrg/Important/UniEmployee/backend/app/subagent_budget.py:19)。脚本和测试配置存在不等于本次已执行或生产已通过验收。

## 5. 优先完善的具体事项

### P0-A：知识权限为空时应拒绝检索

**已确认的数据流：**`kb_search` 根据员工配置生成检索参数；映射全部为空时返回 `None`；RAGFlow 客户端把 `None/[]` 回退为全局 `RAGFLOW_DATASET_IDS`，全局也为空时进一步列出该 API key 可见的全部数据集。

生产预检已要求全局白名单，这是有益的防护，但全局白名单不等于某个员工的授权列表。因此，在工具仍已挂载、员工知识映射为空的条件下，检索范围可能超出该员工所绑定的知识域。这里是源码可见的权限扩大路径，未对真实数据做越权实验。

依据：[工具动态取配置](/Users/wrg/Important/UniEmployee/backend/app/compiler.py:81)、[空映射处理](/Users/wrg/Important/UniEmployee/backend/app/knowledge.py:10)、[范围回退](/Users/wrg/Important/UniEmployee/backend/app/connectors/ragflow_client.py:75)、[生产全局白名单预检](/Users/wrg/Important/UniEmployee/backend/app/startup_preflight.py:64)。

建议：明确区分“管理员显式系统级检索”和“员工授权为空”；后者直接拒绝。有效范围必须是员工授权、用户授权和系统允许范围的交集。知识库选择也需服务端校验，不能只相信前端选项。

验收：员工 A 仅能检索 A；空映射、解除绑定、指定其他知识库时不扩大范围；知识撤权在下一次工具执行时生效。

### P0-B：生产禁止模拟工具声称业务成功

`create_ticket` 当前只生成时间编号和成功字符串，不使用工单系统，也没有工单落库；退款示例使用硬编码订单，审批通过后构造退款号，并返回“3–5 个工作日到账”。审批流程存在，但不代表钱已退或工单已登记。

依据：[工单工具](/Users/wrg/Important/UniEmployee/backend/app/tools/kb.py:7)、[退款执行](/Users/wrg/Important/UniEmployee/backend/app/workflows/refund.py:98)、[工具装配](/Users/wrg/Important/UniEmployee/backend/app/compiler.py:338)、[当前演示连接器禁用范围](/Users/wrg/Important/UniEmployee/backend/app/demo_isolation.py:10)。所查装配路径没有针对这两个本地工具的生产模式拦截。

建议先给工具增加 demo/read/write 分类，生产禁止 demo 写工具；然后选一个真实工单系统完成最小业务闭环。写工具应返回结构化的业务状态、外部单号和核验结果，界面区分“待审批、已受理、执行中、完成、失败、待核验”。

验收：模型不能仅凭文字输出登记成功；重试同一请求不重复建单；只有外部回执和必要读回核验通过后才展示完成。退款等高风险流程最后接入，先验证幂等、审批身份和补偿路径。

### P0-C / P1：凭据分离，再做个人授权连接器

当前 connector config 原样 JSON 存储，管理接口返回完整对象，创建/修改把完整 before/after 写入审计。**若 token/password 放在 env/headers 中，就会被一并复制进这些快照。**这是条件性数据流风险，不是已发生泄露的结论。

依据：[配置存取](/Users/wrg/Important/UniEmployee/backend/app/catalog/resources.py:244)、[管理响应与审计](/Users/wrg/Important/UniEmployee/backend/app/routes/admin.py:358)、[审计序列化](/Users/wrg/Important/UniEmployee/backend/app/audit/__init__.py:15)。模型 API key 也应纳入同一治理，见 [模型配置](/Users/wrg/Important/UniEmployee/backend/app/catalog/ai_models.py:102)。

先实施 `secret_ref`、写入后不回显、审计递归脱敏、日志和错误信息脱敏；再建立三层模型：连接器定义、用户/企业连接实例、员工可用授权。逐步补 PKCE、刷新锁、撤销、scope、探活、失效状态和重连。

验收：配置与审计查询不能取回密钥原文；用户 A 不能调用 B 的授权；token 过期能提示重新授权；共享服务账号有明确的业务范围和负责人。

### P0-D / P1：IM 从通用 webhook 发展为真实办公入口

当前外部入站使用统一 `ImIncomingMessage`；secret 校验是可选的，未绑定员工时回退全部员工，sender_id 来自入站请求；出站是统一 JSON webhook，异常被忽略且未检查 HTTP 失败状态。

依据：[入站身份与员工选择](/Users/wrg/Important/UniEmployee/backend/app/routes/im.py:153)、[出站处理](/Users/wrg/Important/UniEmployee/backend/app/routes/im.py:81)。生产 webhook 密钥预检目前检查的是自动化表，不能据此认为 IM 频道也覆盖，见 [预检查询范围](/Users/wrg/Important/UniEmployee/backend/app/startup_preflight.py:124)。

先收紧外部频道：强制鉴权、未授权员工拒绝、防重放和事件去重、身份映射。之后只选客户实际使用的一个平台接原生 adapter，覆盖群聊/私聊、卡片、附件、消息长度、审批与失败回执。外发通知通过持久 Outbox 记录状态、退避重试和人工处置入口。

验收：平台重复投递不重复执行业务；不同群/用户不串会话和记忆；出站 401/429/500 可见并可处理；IM 触发的审批能定位真实内部身份。

### P1-A：在已有 run 基础上补执行接续和调度隔离

`agent_runs` 已有后台任务与事件重放，但启动恢复会把所有 queued/running 标为 abandoned，并清空活动记录，没有按 worker 实例租约过滤。取消依赖进程内任务字典。若直接部署多个应用副本，第二个实例启动可能误回收其他实例仍运行的记录。这是基于代码的推断，本次未做双实例复现。

自动化已有执行账本、触发去重、CAS 和心跳，仍有两个边界：调度循环逐个 await 长任务，会拖延其他到期任务；推进 next_fire 与执行之间退出时，只能留下中断记录，不能保证自动接续。简单把自实现 cron 换成 APScheduler 不会自动解决这些问题。

依据：[启动回收](/Users/wrg/Important/UniEmployee/backend/app/agent_runs.py:175)、[后台执行](/Users/wrg/Important/UniEmployee/backend/app/agent_runs.py:206)、[调度循环](/Users/wrg/Important/UniEmployee/backend/app/scheduler.py:21)、[陈旧执行处理](/Users/wrg/Important/UniEmployee/backend/app/automations.py:419)。

建议：先分离到期触发和受限并发执行，补持续 stale 扫描与显式恢复策略；需要多实例时再加入 worker_id、租约/心跳、fencing token、共享取消请求和跨实例配置版本。副作用工具有幂等键后，才按故障类型允许重试。

验收：长任务不挡住其他到期任务；故障注入后没有永久 running；安全任务可恢复，写操作不重复；第二副本启动不影响首副本活动任务。近期坚持单实例时，多实例部分可后移，但应明确部署边界。

### P1-B：把评测、版本、模型与成本连成发布闭环

现有评测功能是真实运行员工并保存结果，已经有价值。但目前以管理员身份运行、人工评分，单次最多 25 个用例，后台执行依赖应用进程。管理员用例通过不能证明普通用户权限正确；`completed` 不能等同答案 `pass`。

依据：[运行身份](/Users/wrg/Important/UniEmployee/backend/app/routes/admin.py:714)、[触发与配置 hash](/Users/wrg/Important/UniEmployee/backend/app/routes/admin.py:761)、[人工评分](/Users/wrg/Important/UniEmployee/backend/app/routes/admin.py:801)、[黄金集边界](/Users/wrg/Important/UniEmployee/tests/fixtures/golden_eval/README.md)。

建议在现有功能上增加：

- 业务负责人批准的用例集，包含正常、无答案、冲突、过期、越权、工具失败和审批恢复。
- 使用普通用户/部门等不同身份运行；对引用、工具结果、业务记录和产物做确定性断言。
- 发布版本固定 persona、skill/SOP、工具 schema、connector、模型和数据版本；评测基于固定快照，保留历史回放依据。
- 草稿→评测→复核→发布→回滚；配置热失效继续保留，但每次运行明确记录使用的版本。
- 借鉴 Octop 的模型调用层健康切换，限定批准的供应商、数据驻留和能力要求；不能因故障绕过审批或重放整条写流程。
- 现有 token/耗时统计发展为按价格版本记账的费用、员工/部门预算、单任务 token/工具/时间限额及告警。并发准入目前是 process-local，默认关闭，不能等同费用配额。

验收建议：先选一个员工和一套真实问题集，发布必须通过业务批准的质量/权限阈值；能比较前后版本质量、P95 耗时和单任务成本。模型故障切换不触发重复业务写入。阈值由业务 owner 和试点基线确定，本文不冒充已达标。

### P2-A：把长期记忆变成可检查、可纠正、可删除的数据

UniEmployee 已有按 user×employee 隔离的持久 Store 和自动加载的 `AGENTS.md`，应保留这个基础。当前所查用户路由和前端尚未形成 Octop 那样的专属记忆管理链路。

依据：[记忆初始化](/Users/wrg/Important/UniEmployee/backend/app/runtime.py:169)、[命名空间与装配](/Users/wrg/Important/UniEmployee/backend/app/compiler.py:516)、[加载入口](/Users/wrg/Important/UniEmployee/backend/app/compiler.py:692)。

先做“员工记住了什么”：来源会话、记录时间、有效期、用户纠正/删除、禁止记忆的敏感字段、离职清理。再按需要拆个人偏好、业务事实和任务经验；业务事实应保留源系统核验，避免把过期记忆当主数据。无需先引入整套新向量存储。

验收：错误记忆可纠正，删除后不再注入；跨用户不可见；客户、价格、合同状态等动态事实仍查询授权业务源。

### P2-B：员工包、协作与交付物围绕一个真实场景扩展

在现有资源中心上增加 EmployeePackage：manifest、版本、技能/SOP、工具/连接器依赖、最小授权、兼容版本和评测集。导入先预检与试运行，升级显示差异并支持回滚；不打包密钥、个人记忆和聊天记录。先做内部能力包，无需立即开放 Python 动态插件市场。

在现有子代理基础上试一个跨员工任务，例如“售前收集需求→分析员工核算→售前形成方案→负责人复核”。需要任务/子任务记录、依赖、授权、超时取消、预算、结果引用和统一交付；确定性审批仍用状态机。不要把多人聊天展示当作任务可靠性。

在已有产物归档和部门 ACL 上增加来源链、业务复核状态、版本与显式发布；需要多节点时再抽象对象存储。给 net-ops 展示沙箱输出、截图和执行证据，人工接管按具体 GUI 业务引入。

依据：[子代理装配](/Users/wrg/Important/UniEmployee/backend/app/compiler.py:474)、[本地产物快照](/Users/wrg/Important/UniEmployee/backend/app/artifact_storage.py:14)、[部门共享与预览权限](/Users/wrg/Important/UniEmployee/backend/app/routes/workspace.py:109)。

验收：员工包可在干净环境导入并通过基准；协作失败能定位责任步骤；交付物能追溯输入、员工版本与审批，未授权用户不能通过文件链接绕过 ACL。

## 6. 工程与运维的增量完善

这部分不应取代业务闭环，但能降低后续扩面的成本：

- **渐进门禁。** 保留现有 SQLite/PG CI，加 Ruff 与增量类型检查；前端先加组件测试和登录→任务→审批→产物下载的关键用户流测试。无须为了对齐 Octop 改用 React。Octop 的前端有 TS/Vitest 配置，但其所查 PR CI 也不能简单等同每个前端测试都自动执行。依据：[Octop CI](/Users/wrg/mystudy/Octop/.github/workflows/ci.yml)、[Octop 前端脚本](/Users/wrg/mystudy/Octop/dashboard/package.json:6)、[Uni 前端脚本](/Users/wrg/Important/UniEmployee/frontend/package.json:6)。
- **可追踪迁移。** Uni 目前通过多个模块的建表和幂等 ALTER/backfill 演进；下一步建立统一迁移版本、升级记录、失败策略和旧版本数据库升级测试，覆盖 7 个库。Octop 有编号双数据库迁移可参考，但其迁移模块也有大量 legacy repair，没必要照搬复杂实现。依据：[Uni catalog 迁移](/Users/wrg/Important/UniEmployee/backend/app/catalog/db.py:124)、[Octop 迁移入口](/Users/wrg/mystudy/Octop/src/octop/infra/db/migrate.py:2057)。
- **运维可验收。** 已有联合备份和恢复脚本，补定期执行、离站加密存储、保留策略、恢复报告与明确 RPO/RTO；数据库与文件的一致性尤其要验证。不能把备份脚本存在等同业务可恢复。指标按任务成功、模型/工具失败、审批积压、投递失败、成本、容量定义，并连接到值班责任人。
- **权限按需求深化。** 当前 `AuthContext` 仍有 admin/user 固定集合；单企业先补资源 owner、部门和业务数据域权限矩阵。多个独立企业共用实例之前，再做 catalog、数据源、连接器、知识、文件、trace 等全链路租户隔离专项。依据：[授权上下文](/Users/wrg/Important/UniEmployee/backend/app/auth_context.py:9)。
- **文档随版本校验。** 更新开发指南中已过时的 seed、缓存、CI 和备份描述，避免后续 AI Coding 重复建设或基于错误前提改动。

## 7. 建议实施顺序与验收产出

下面是工作顺序，不是固定工期承诺。每阶段以一名业务 owner 负责的实际任务验证。

| 阶段 | 最小交付 | 退出条件 |
|---|---|---|
| 1：先收紧边界 | 空知识授权拒绝；生产禁模拟写工具；密钥脱敏；外部 IM 默认拒绝未授权请求 | 有针对性回归；无扩大知识域、虚报完成或密钥回显 |
| 2：完成一条业务链 | 一个真实连接器、一个真实工单动作、审批、回执核验、一个实际 IM | 业务系统记录可查；重复请求不重复操作；失败可人工接管 |
| 3：运营可持续 | 固定版本评测、普通用户授权用例、费用预算、模型故障策略、调度隔离 | 发布可比较/回滚；故障可解释；长任务不阻塞调度 |
| 4：复制到更多岗位 | 员工包、记忆管理、跨员工协作、交付物来源链 | 新岗位可复用部署；产物/责任/授权可追踪 |
| 按扩容需求推进 | 分布式租约、取消路由、配置版本传播、共享文件存储 | 双实例故障验证通过后再承诺多副本运行 |

业务效果至少跟踪：任务完成率、业务核验成功率、人工接管率、引用可追溯率、工具成功率、审批耗时、P95 完成时间、单任务费用和节省人工时间。越权、虚假完成和错误外部写操作独立统计，不用平均满意度掩盖。

## 8. 暂不建议优先投入的方向

MBTI 人格、家庭/娱乐专家、桌面客户端、全平台 IM、全功能远程桌面、通用插件市场、ACP 编码 runner、跨实例专家市场，都不是当前企业主线的第一优先级。可依据明确客户场景单独投入。

同样，不建议替换 deepagents/LangGraph、重写前端、先拆微服务或先引入大型队列平台。Octop 自己采用单进程、无外部队列架构，也明确限制水平扩展，见 [单进程 ADR](/Users/wrg/mystudy/Octop/docs/adr/001-single-process-model.md)。应先用现有数据表和执行链路补业务状态、幂等、租约与可观测，再以实测容量决定基础设施。

Octop 的本地知识索引在查询时读取 chunks 并做进程内余弦排序，适合它的轻量自托管目标；这不是替换 UniEmployee RAGFlow 的充分理由。更值得借鉴的是可检查的引用和用户可见范围。见 [索引查询](/Users/wrg/mystudy/Octop/src/octop/infra/knowledge/index.py:98)、[可见知识库筛选](/Users/wrg/mystudy/Octop/src/octop/infra/knowledge/retrieve.py:88)、[结构化引用](/Users/wrg/mystudy/Octop/src/octop/infra/knowledge/citations.py:13)。

## 9. 本次验证范围

本次交付为研究报告，未修改业务代码、未提交或推送 Git。做了源码路径/行号核对、两仓当前提交核对、报告链接校验；未运行 pytest、前端构建、真实模型评测、备份恢复或故障注入。因此本文没有声称测试通过、实际越权已复现、生产高可用或任何业务指标已达标。
