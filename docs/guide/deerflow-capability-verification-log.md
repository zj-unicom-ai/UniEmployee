# UniEmployee × DeerFlow 能力验证台账

> 按《[价值驱动迭代决策方案](./deerflow-value-driven-iteration-plan.md)》逐项验证。状态只代表已记录的证据范围；合成数据技术通过不等于业务验收。最近更新日期：2026-09-27。

## 总体状态

| 优先级 | 项目 | 状态 | 当前结论 |
|---|---|---|---|
| P0-A | 单场景数据接入与演示数据隔离 | **生产播种及已知模拟 CSV 门禁通过；发布条件未通过** | 新库不播种演示本体或指派实验 CRM；已知模拟 CSV 阻止生产启动，RAGFlow/历史产物与真实数据授权待核验 |
| P0-B | 业务评测与发布门槛 | **技术基线通过；业务门槛待定** | CRM Lab 3/3 技术用例通过；缺真实业务样本、owner 签收和风险门槛 |
| P0-C | 试点最小生产保障 | **隔离备份恢复及编译层执行隔离通过；生产就绪未通过** | 7 库 + workspace 已完成隔离恢复演练；生产沙箱服务实测和 RPO/RTO 签收仍未完成 |
| P1-D | 长任务独立运行与重新连接 | **单实例 Docker 浏览器断线重连验收通过；生产运行环境与业务价值未验收** | 合成任务在页面离开后继续运行，重开会话能回放完整事件并完成；服务重启续跑、多实例租约和真实任务收益仍未验证 |
| P1-E | 定时任务可恢复与可追责 | **单实例 Docker 幂等、历史与人工重跑验收通过；无人值守业务验收待做** | 同一 Webhook key 重放返回原执行且不创建第二个 Agent run；管理页显示失败/成功重跑两条记录；停机漏点仍合并补跑一次，无自动重试 |
| P1-F | 模型准入、超时与成本预算 | **单实例技术护栏部分通过；金额预算/业务门槛未通过** | 可按模型限制 Agent run 并发、排队、拒绝并设置 OpenAI 兼容请求超时；默认关闭；跨进程配额与货币预算未完成 |
| P2 | 子代理次数与并发预算 | **按配置启用的单实例技术闭环部分通过；深层通用子代理边界待补** | 公共 LangChain middleware 已给主 Agent 和显式配置子代理加每次运行总次数限制及顶层并发限制；默认关闭；自动注入 general-purpose 子代理的内部递归调用未完全受限 |

“待验证”不是通过或失败。P1/P2 是否值得实现，仍按方案中的业务损失和触发条件判断。

## P0-A：单场景数据接入与演示数据隔离

**结论：生产播种隔离的限定范围已复验通过；整体发布条件未通过。** 当前可证明只读连接器技术上能连接本地合成 CRM；不能证明真实数据授权、身份映射或业务准确率。此次修复让 `APP_ENV=production` 的新库跳过演示本体播种、跳过 mock CRM/CRM Lab 登记与指派，并在旧库残留演示种子或指派时明确报错。既有本地演示容器仍按开发模式运行，数据未被自动删除。

### 已验证通过的部分

- UniEmployee Docker `/health` 与 CRM Lab `/healthz` 均返回 `200`；CRM Lab API 当前状态为 `ok`。
- 已有的 CRM Lab 集成验证记录了四个只读 MCP 工具、只读密钥访问、写操作 `403`、错误密钥 `401`，以及宿主机/容器网络下的 Agent 查询，见[集成验证记录](./crm-lab-integration-validation.md)。本轮评测 Trace 进一步证实 3 个基准用例只调用 CRM Lab 工具。
- `crm_lab` 连接器明确描述为本地合成数据读取；连接器只通过 HTTP `GET` 读 CRM Lab，缺少只读密钥时拒绝调用，见 [`crm_lab_server.py`](../../backend/app/connectors/crm_lab_server.py)。CRM Lab 由同级目录独立 Compose 服务提供，见 [`docker-compose.crm-lab.yml`](../../docker-compose.crm-lab.yml)。
- 新库默认指派列表 `CONNECTOR_ASSIGN` 没有 `crm_lab`；生产模式还跳过 `crm`/`crm_lab` 登记与指派，编译层禁止加载这两个演示连接器。当前验证容器的隔离数据库曾为 `xiaoxiao` 手动绑定 CRM Lab，它仍是开发模式演示配置，见 [`seeds.py`](../../backend/app/catalog/seeds.py)、[`demo_isolation.py`](../../backend/app/demo_isolation.py)。
- 全新、临时的 PostgreSQL 生产模式库完成 catalog 与 ontology 播种复验：mock CRM 连接器和指派均为 0，default 租户的实体和关系均为 0；验证后两库已删除。对现有隔离 PostgreSQL 演示库做只读生产预检，已按预期拒绝其演示 CRM 指派。SQLite 临时库对“生产新库为空”“旧演示库拒绝切换生产”“运行时拒绝实验连接器”均通过。
- 2026-09-27 清点当前 `workspace`：共有 140 个文件，其中 `data/` 下 115 个、`datasets/` 下 5 个、两套本地知识文档 19 个及一个系统文件。5 个共享 CSV 是 `crm_contracts`、`crm_opportunities` 与 3 个 `netops_*` 生成数据集；生产预检现对这些已知文件在 `workspace/data` 或 `workspace/datasets` 中出现时拒绝启动，单元测试通过。未读取或删除 `data/` 中的用户产物。
- 当前配置的 RAGFlow 只读列举返回 9 个知识库，包含“客户档案”“算网运营知识库”“浙江联通业务知识库”等。列表本身无法证明内容是真实还是演示，也无法确认授权；不能把名称当作生产数据证明。
- 相关 catalog、本体、MCP 回归测试此前 50/50 通过；当前工作树后端全量测试为 **561 passed、40 skipped**。40 项按仓库规则因 `8787` 没有集成测试服务而跳过；当前 `8788` Docker 演示容器尚未重建，继续作为开发环境运行。

### 未通过 / 未具备条件的部分

1. **没有真实数据源可验。** 当前唯一外部 CRM 服务是 `CRM Lab`，数据明确为合成数据；缺少真实系统地址、只读账号、授权范围、字段映射和数据 owner。因而“真实数据接入”这一半无法判为通过。
2. **旧演示库需要人工核对。** 现有验证容器的 `tenant=default` 查询仍可见“吉利汽车”演示客户；当前运行镜像也尚未重建。新生产模式会对 default 租户 `source=seed` 的实体/关系及演示 CRM 指派拒绝启动，避免静默带入；但这些历史数据不能在缺乏来源复核时自动删除。已审核的合法 `seed` 记录需要先明确迁移或重新标记来源。
3. **其他演示资产已列目录，来源仍待核对。** 5 个已知模拟 CSV 已加入生产门禁；`workspace/data` 的 115 个文件、本地知识文档与 RAGFlow 的 9 个知识库还须按试点数据范围逐项核查来源、授权和租户归属。旧 mock [`crm_server.py`](../../backend/app/connectors/crm_server.py) 的返回体本身也没有统一 `synthetic: true` 标识，开发环境中的回答仍须显式说明来源。

### 价值判断与验收条件

改进的价值是防止用户把模拟客户、合同或订单当成真实业务事实；如果错误事实进入拜访、续约或经营判断，影响大于“多接一个工具”带来的便利。当前不能对外展示为真实 CRM 试点。

完成此项需分别满足：

1. 新建生产模式数据库后，不自动出现演示客户、合同、网络运营实体或默认 mock CRM 员工授权；此项已在临时 PostgreSQL 验证。已存在的演示数据仍需执行经审核的隔离/迁移路径。
2. CRM Lab、mock CRM 与生产业务连接器在名称、来源标记、租户范围和授权上可区分；任何合成记录都能在回答和审计中识别。
3. 接入真实只读数据源后，由数据 owner 确认字段授权、更新时间、空结果与越权行为；业务方用真实任务样本签收。

**下一动作：**由数据 owner 核对现有 workspace/RAGFlow 内容和旧库记录，制定保留/迁移/隔离清单；真实数据接入需用户提供目标系统、授权 API 与数据 owner。生产播种与已知文件门禁的技术复验不能替代真实业务发布验收。

## P0-B：业务评测与发布门槛

技术基线已运行：评测集 `es_5f7dc3b8261d4317`，运行 `ebr_af7e824adcee49dd`，3/3 人工判定通过。用例、配置 hash、Trace、耗时和 token 统计见[评测基线记录](./crm-lab-integration-validation.md#现有评测工作台回归基线)。这只证明现有评测工作台可用于本地只读技术回归；业务 owner、真实问题样本、风险分层与发布阈值仍待确认。

## P0-C：试点最小生产保障

**结论：隔离备份恢复演练通过，生产就绪核验仍未通过。** 本轮在隔离 PostgreSQL 容器上创建临时库进行恢复，没有对用户主数据库做备份或恢复操作。

### 验证发现

1. **七库与文件的隔离恢复已通过。** [`scripts/backup.sh`](../../scripts/backup.sh) 现将七个 PostgreSQL 自定义格式 dump、`workspace` 和清单放入同一归档。2026-09-27 使用 [`verify_backup_restore.py`](../../scripts/verify_backup_restore.py) 在隔离 PostgreSQL 容器创建 7 个源库和 7 个目标库，逐库写入探针，备份后恢复到全新目标库，逐库核对探针并核对临时 `workspace` 文件；结果 `backup_restore_passed databases=7 workspace_files=1 elapsed_seconds=3.25`，随后删除 14 个临时库。这证明备份内容与恢复路径可用，不代表真实数据量下的 RTO。普通在线备份为逐库/文件非同一时点；要取得一致恢复点需先由运维暂停应用写入，清单中的 `BACKUP_QUIESCED=1` 只记录这一操作。
2. **编译层已禁止生产执行型员工落到宿主机。** [`compiler.py`](../../backend/app/compiler.py) 在 `APP_ENV=prod/production` 或 `REQUIRE_SANDBOX=1` 时，将 `local_shell` 员工也路由到 OpenSandbox；未启用 `SANDBOX_ENABLED` 则报错。原有 `sandbox` 员工同样禁止生产回退。开发模式下的 LocalShellBackend 已改为 `inherit_env=False`，只传 `PATH`，单元测试确认不会继承应用 `JWT_SECRET` 环境变量。`tests/test_sandbox_mgr.py` 27 项通过。此验证仅到编译层，尚未实测生产 OpenSandbox server 创建容器与业务数据挂载。
3. **执行进程的完整凭据边界仍待实测。** Compose 通过 `env_file: .env` 将应用密钥传入主进程；开发模式下 LocalShell 的 shell 环境已不继承这些变量，但宿主机文件系统仍可被 shell 访问，因此开发模式不得承载真实试点数据。生产模式需要沙箱服务及挂载权限实测。CRM Lab MCP 只获连接地址和只读 API Key。
4. **恢复目标没有业务签收。** 当前尚无试点 owner 定义 RPO/RTO、备份保留期限或恢复验收标准；不能仅凭脚本存在认定恢复能力通过。

### 验收条件与下一步

- 七库及 workspace 的隔离恢复路径已通过；下一步在授权试点数据量上做暂停写入的一致备份，恢复到独立环境后核对真实会话/Trace、用户文件与生成产物，并记录 RPO/RTO。
- 生产部署显式启用生产模式；执行型员工未启用 OpenSandbox 时明确不可运行，编译层已通过。下一步实测沙箱服务、工具与挂载边界，以及无授权员工无法读取主进程密钥或宿主机文件。
- 由试点 owner 签收实际 RPO/RTO、保留周期与可用工具范围；上述技术演练通过后，再将 P0-C 标为通过。

## P1-D：长任务后台运行与重新连接

**结论：单实例技术闭环通过，生产运行环境与业务价值验收仍未通过。** 2026-09-27 将 Web 消息和审批恢复改为后台 Agent run；SSE HTTP 请求只订阅数据库事件。新增运行/事件表、同会话单活跃运行约束、游标重放、取消、7 天事件清理、启动时遗留任务收敛。浏览器断线或切换页面不会取消 Agent；重开会话可恢复活跃 run。审批恢复（含退款内层 StateGraph）也在后台执行，减少审批决定已写入但浏览器断开导致恢复中断的窗口。

### 可复现技术证据

- tests/test_agent_runs.py 覆盖运行唯一性、状态转换、取消、进程启动遗留恢复、订阅断开后后台继续、事件游标重放、事件过期反馈、租户/用户授权，以及 HTTP 消息入口和事件/状态查询；最近运行 8 项通过。
- 全量后端回归 **550 passed、40 skipped**；前端 npx vite build 成功。
- scripts/verify_agent_runs_postgres.py 在隔离 PostgreSQL 容器的临时库实测创建/更新/回放运行事件，通过后删除临时库。
- 前端 Chat 与 Analyst 工作台均调用活跃 run 查询并从游标恢复；用户点击“停止”会请求取消 Agent；HTTP 返回的 run id 与事件序号供续接使用。
- **2026-09-27 Docker 浏览器断线重连实测通过。** 在当前 8787 Docker 应用中以 `P1-D Local Fake` 临时模型接入本地 OpenAI 兼容慢速桩，模型配置在验收后删除，没有请求 DeepSeek。第一轮确认真实聊天 UI 收到分块流式响应；第二轮在收到 `ROUND2_PARTIAL_MARKER` 后离开会话页，再打开同一会话。页面恢复时后台 run 仍为 `running`，随后 UI 收到并显示完整回答。数据库中 run `ar_28dbd1e20210482d99b747415e4925b4` 最终为 `done`，Trace `r_54840e480df84348` 为 `done`、1 次 LLM 调用、0 次工具调用；11 条运行事件的序号为 1–11 连续且无重复，开始/中段/结束标记在最终页面各出现 1 次。临时模型记录、本地模拟服务和浏览器登录态均已清理。该证据验证的是单实例 Docker + 合成模型路径。

### 尚未通过的边界

1. 当前后台 task 所有权保存在应用进程内；应用进程重启后任务被标记为 abandoned，不自动续跑。多 worker/多实例的租约接管与跨进程取消未实现，因此当前只承诺单应用进程部署。
2. Docker 演练使用本地合成模型桩，不验证真实模型供应商、真实长任务时延或生产容量；尚无真实任务的断流率、重跑率、完成率和成本基线，无法量化业务收益。

## P1-E：自动化任务执行账本、幂等与人工恢复

**结论：单实例技术闭环通过；真实无人值守任务与运营收益未验收。** 原实现只更新自动化配置上的 `last_status/last_error/run_count`，无法回答哪一次 Cron、Webhook 或手动运行失败；Webhook 重投会再次调用 Agent。现在新增 `automation_executions` 逐次记录、按事件唯一键去重、心跳超时转 `interrupted`、管理员执行历史查询和人工重跑；不自动重试，避免副作用工具被重复调用。

### 为什么值得做、做好后的价值

- 当任务用于日报、巡检或告警处理时，单个“最近状态”无法定位漏跑/重跑原因，人工只能查看日志并猜测是否执行。独立账本使每次触发有稳定 ID、触发类型/键、会话、状态、错误和重跑关系，可审计、可支持运维处理。
- 外部系统超时后重发 Webhook，之前可能重复创建会话并再次执行工具。调用方提交同一 `Idempotency-Key` 后，重放返回原执行记录，不再启动第二个 Agent，降低重复通知、重复写入等风险。
- 进程崩溃留下的 `queued/running` 记录会在心跳过期后变为 `interrupted`，管理员能判断会话后选择是否重跑。没有自动重试，因为“写入工单/发通知”等工具可能已有部分副作用。
- 事件 payload 不被复制到执行账本；事件任务人工重跑时由管理员重新提交 payload，避免系统为恢复功能额外保存一份可能含个人信息的原始请求。

### 实现与技术验收证据

- [`automations.py`](../../backend/app/automations.py) 持久化每次执行；唯一键为 `(automation_id, trigger_type, trigger_key)`。Cron 在 CAS 抢占前先创建记录，尽量消除“已抢占、还没留执行记录”的崩溃窗口；计划触发时间作键。Webhooks/人工重跑要求客户端提供 `Idempotency-Key`，长度 1–200。
- [`scheduler.py`](../../backend/app/scheduler.py) 保留既有 CAS 和停机漏点合并策略；重复 Cron key 不会重复启动任务。执行心跳每 20 秒更新，启动时将超过 120 秒无心跳的 queued/running 标成 `interrupted`。已结束记录默认保留 90 天（`AUTOMATION_EXECUTION_RETENTION_DAYS` 可调整）。
- [`routes/automations.py`](../../backend/app/routes/automations.py) 提供管理员执行历史和失败/中断人工重跑接口；[`AutomationView.vue`](../../frontend/src/views/AutomationView.vue) 增加执行历史和重跑确认。
- `tests/test_automations.py` 和 `tests/test_automation_execution_routes.py` 覆盖唯一键重放、Agent 不重复执行、失败后重跑链路、超时恢复、Webhook 缺失 key 拒绝、管理权限和前后端路由行为；定向测试 **26 项通过**。
- [`verify_automation_executions_postgres.py`](../../scripts/verify_automation_executions_postgres.py) 在隔离 PostgreSQL 临时库实测唯一键、超时恢复和 retry lineage，通过后删除临时库。
- `npx vite build` 通过，Automation 页面产物正常构建。
- **2026-09-27 当前 Docker 应用端到端实测通过。** 建立仅用于验证的 HRBP 事件自动化，执行模型临时路由到本地 OpenAI 兼容模拟器（第一轮故意返回 400，后续调用返回合成成功文本）；原模型 API 域名和密钥在结束后从数据库备份行恢复，未请求 DeepSeek。Webhook 首次调用生成失败执行 `aex_058fda73085f4c26b952d4e8ad88b2c0`；相同 `Idempotency-Key` 重投返回同一 execution ID、`duplicate=true`，数据库仍只有一条 `event` 记录且没有第二个对应 Agent Trace。管理员用新的 key 人工重跑后生成 `aex_7b638e256b7040158eae64c1e20451da`，状态 `ok`，回复为合成标记 `P1E_RETRY_SYNTHETIC_SUCCESS`，`retry_of` 正确指向失败记录。两个 Trace 分别为 error/done，各 1 次模型调用、0 次工具调用。自动化管理页面实际展示两条历史记录和人工重跑确认/payload 表单；确认框验后取消，未多发起执行。测试自动化保留为禁用状态供管理员查看，模拟模型、备份模型行和临时服务均已清理；`/health` 恢复正常。

### 仍未通过的边界

1. 停机期间错过的 Cron 仍合并补跑一次，并不逐个补齐计划点；是否需要逐次补跑要由真实任务的时效性决定。
2. 自动化执行目前仍在应用进程内运行；心跳超时只标记中断，不会从 LangGraph checkpoint 自动恢复 Agent。
3. Webhook 调用方必须持久化并重用 `Idempotency-Key`；不支持稳定 key 的上游目前无法获得重试去重保证。
4. 未接入真实无人值守业务，也没有“重复执行损失、漏跑率、人工处理时间”基线；因此工程可用性通过不代表 ROI 或业务发布通过。

真实无人值守任务尚未接入，也没有漏跑率、重复副作用损失或人工处理时长基线；因此本次证明的是 Docker 技术链路，不等于业务 ROI 或无人值守发布验收。上线前仍需业务 owner 决定漏点补跑策略、任务时效和允许副作用范围。

## P1-F：模型准入、超时与成本预算

**结论：单实例负载护栏已实现并通过定向验证；跨进程准入、货币预算和容量目标尚未验收。** 原系统可从 Trace 查到部分 token 用量，但没有统一模型级运行并发、排队上限和等待拒绝；模型供应商 API 也未统一应用请求超时。

### 改造为什么有价值

- 突发流量可能同时启动许多 Agent run，打满同一个模型配额后全体收到 429。按模型准入、有限排队能控制单实例同时运行数量，并在等待超时时给用户稳定反馈，减少无意义的持续等待和上游重试风暴。
- 单次模型 API 调用超时能从卡住的上游请求中返回；它只约束模型调用，不误杀可能需要更长时间的本地工具。
- Trace 和准入统计提供按模型查看拒绝与等待的起点。**目前没有价格表、合同费率和业务费用额度，不设置伪精确的金额硬上限**；金额预算需先由 owner 给费率和每任务/日限额。

### 实现与验证

- [`model_admission.py`](../../backend/app/model_admission.py) 对每个模型限制 Agent run 并发；`MODEL_MAX_CONCURRENT=0` 默认关闭。启用后由 `MODEL_MAX_QUEUE` 限排队长度、`MODEL_QUEUE_TIMEOUT_SEC` 限等待时间；超限写入 Trace 并返回 `model_capacity_exceeded`。
- [`compiler.py`](../../backend/app/compiler.py) 对 OpenAI 兼容模型设置 `MODEL_REQUEST_TIMEOUT_SEC`（默认 120 秒，0 则采用 Provider 默认值）。非 OpenAI 兼容字符串模型目前不会注入该 timeout。
- 管理员 API `/api/admin/ai-models/admission` 返回本进程活跃数、等待数、接纳/拒绝累计、平均/最大/P95 等待；指标是进程内存统计，服务重启归零，未作为经营账单或持久化 SLI。
- 最新源码 Docker 验证实例中该管理员 API 返回 200，默认 `enabled=false` 与配置一致；实例没有配置真实模型凭据，所以没有进行容量负载、队列等待或 OpenAI 兼容模型超时的容器压测。
- `tests/test_model_admission.py` 覆盖并发槽、队列拒绝与释放、关闭默认、OpenAI 兼容超时注入；`tests/test_model_admission_route.py` 覆盖管理员接口；`tests/test_streaming_admission.py` 验证流入口超限拒绝和 Trace 收尾。与 P1-E 的定向测试合计 **32 项通过**。
- 全量后端回归 **556 passed、40 skipped**；前端生产构建通过。Vite 提示现有入口 bundle 超过 500 KB，此次没有改变其分包策略。

### 未通过边界与下一步

1. 准入槽覆盖整个 Agent run（工具执行等待也占槽），并非每一次独立 LLM 子调用；阈值按单个进程生效，多 worker/多容器无共享协调。
2. 统计是进程内短期观测，不跨重启；没有按模型/员工/任务成本持久化、429 比率/P95 仪表盘和告警。
3. 没有供应商费率、模型价格配置或业务预算，不能声称“成本硬上限已实现”。
4. Docker 版本与真实模型高峰压测尚未验收；默认关闭的准入配置还要由容量观测决定是否开启以及设值。

下一步在 Docker 验证容器中用低并发阈值和可控慢模型桩做并发占槽/排队超时演练，不发起真实付费压测；成本上限的规则等价格和预算 owner 输入后再设计。

## P2：子代理调用次数与并发预算

**结论：按配置启用的单实例技术闭环部分通过；deepagents 自动注入的 general-purpose 子代理内部递归调用不承诺完全受限。** 改造前员工可以反复调用内置 `task`，system prompt 的建议不是硬限制；子代理调用次数和并发扩张缺少确定的技术边界。

### 为什么要限制、做完后的价值

- 子代理适合并行调研，但错误规划可能导致重复委派，增加模型费用和完成时长；如果同一轮过度并行，还会加剧 P1-F 的模型 429。
- 每轮最多调用次数能给委派放大设硬上限；并发上限约束主 Agent 同时启动的子任务数；超限会产生可见的 ToolMessage error，主 Agent 可以继续使用已获得的信息并向用户说明。
- 它解决“异常委派放大”，不会让本来不用子代理的普通问答更准确。上线后要对比每任务 task 调用数、委派超限率、总 token、P95 时长和任务通过率；如果基线显示几乎不触发或没有明显成本，默认可继续关闭。

### 实现与验证

- [`subagent_budget.py`](../../backend/app/subagent_budget.py) 用 LangChain 公共 `AgentMiddleware.awrap_tool_call` 拦截 `task`；没有改动 deepagents 或 LangGraph 第三方源码。`SUBAGENT_MAX_CALLS_PER_RUN` 限一次主 Agent 运行及显式子代理内部的调用总数；`SUBAGENT_MAX_CONCURRENT_PER_RUN` 限主 Agent 顶层 task 并发；`SUBAGENT_QUEUE_TIMEOUT_SEC` 控制并发槽等待。
- 编译器只在次数或并发策略非零时装配 middleware，避免默认行为改变；策略通过进程环境配置，改动后重启并重编译 Agent 生效。执行结束的应用日志按 Trace ID 记次数、拒绝数、峰值并发与总等待，不记录任务输入内容。
- 显式配置的 inline subagents 会共享总次数预算，但不再各自获取并发 semaphore，避免父 task 持有并发槽等待子 task、造成递归死锁。deepagents 自动加入的 general-purpose 子代理，其内部递归 task tool 当前不一定经过 UniEmployee middleware；对它只限制进入该子代理的外层调用。这是明确的覆盖边界。
- `tests/test_subagent_budget.py` **5 项通过**，包括一次真实 `deepagents.create_deep_agent` 假模型图：同轮两次 `task` 请求只放行一个子代理，另一调用收到超限 ToolMessage，主 Agent 仍正常完成；另覆盖并发槽/等待统计、普通工具不受影响、编译器按需安装 middleware。该真实图验证了 LangChain middleware 可在 deepagents 0.7.13 的工具执行链生效，不访问付费模型。深层通用子代理递归和真实 Trace 持久对账仍未验收。
- 最新全量后端回归为 **561 passed、40 skipped**；`git diff --check` 通过。40 项仍是依赖 `8787` 在线的既有容器集成测试，不能当作 P2 Docker 超限演练。

### 仍未通过的边界

1. 两个 limit 默认都是 0（关闭），尚未有真实员工子代理调用数据来确定合适值。
2. 并发上限在主 Agent 顶层 task 委派生效；显式配置的子代理总次数受限但内部并发不受同一 semaphore 控制；自动 general-purpose 子代理内部递归调用还有缺口。
3. 计数在一次 `_stream_run` 上下文内、单进程有效；没有持久化每 run budget summary 字段、跨进程共享配额或管理页监控图。
4. 没有模型/业务 owner 给出的 token/费用限额；次数预算不能替代货币成本硬预算。

下一步用真实 Docker 配置一个很低的次数阈值，验证 Task 超限是否出现在对话工具事件和 Trace 中；然后决定是否为 deepagents 的 general-purpose 子代理做版本兼容原型。在确认真实调用模式前，不把默认额度写成固定业务政策。

## P1/P2：现状核验（尚非目标能力验收）

2026-09-27 对 streaming.py、scheduler.py、automations.py、compiler.py 与 Trace 实现进行源码核对；相关 42 项单元测试全部通过。现有行为得到复核：断流取消并保存部分回复；定时任务 CAS 抢占与结果状态；子代理配置、事件与 Trace。P1-D 后续实现见上节。其他测试未覆盖进程崩溃、跨实例抢占或模型服务高峰。

| 项目 | 当前可证明的能力 | 目标验收仍缺的证据 |
|---|---|---|
| P1-D | 单实例后台执行、取消、事件游标重放、HITL 后台恢复和重启遗留状态收敛 | 实际 Docker 浏览器断网演练；跨进程租约及重启续跑；真实任务的断流损失及收益 |
| P1-E | 执行账本、Cron/Webhook 幂等键、心跳超时发现、管理员人工重跑 | Docker 当前应用演练；漏点是否逐个补齐由真实任务时效性决定；业务收益仍无基线 |
| P1-F | 单进程按模型 Agent run 准入、有限队列、拒绝反馈、OpenAI 兼容请求超时、运行时等待指标 | Docker 慢模型桩实测；跨进程配额；成本费率/硬预算与真实 429、P95、任务成本基线 |
| P2 | 按配置启用的主 Agent task 次数上限/顶层并发限制、超限工具反馈 | general-purpose 递归覆盖；Docker/Trace 验证；基于真实成本基线配置额度 |

代码级目标现已分别补入 P1-D、P1-E、P1-F 的验证章节；P2 仍处于现状核验。测试通过仅证明指定技术路径，不证明真实业务收益、跨实例能力或生产发布门槛。
