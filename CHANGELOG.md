# Changelog

## 0.13.0 (2026-09-09)

### 重磅变更：net-ops 试点接入 OpenSandbox 沙箱执行环境

- **代码执行与文件操作从宿主机直接 subprocess 迁移到 OpenSandbox 沙箱容器**：net-ops（小网·算网运营专家）的 `execute` / 文件工具不再在 app 宿主机直接执行，而是按会话（thread_id）路由到专属沙箱容器（OpenSandbox server 起 docker 容器，TTL 30 分钟空闲回收，重启可重连）。每个会话一个沙箱、容器间互不影响；**沙箱不可用时明确报错，不回退宿主机执行**（避免安全机制失效）。`SANDBOX_ENABLED=1` 全局开关；未置 1 时回退 LocalShellBackend（开发/测试/未部署 server 环境零行为变化）。

- **数据布局重构以支持多租户隔离**：用户上传与生成文件从 `workspace/data/uploads/<uid>/<conv>/` 调整为 `workspace/data/<uid>/uploads/<conv>/`，沙箱内 hostPath 挂载按 `<uid>` subPath 限定本用户目录可见性（沙箱内 `ls /data` 看不到其他用户）；共享数据集（算网运营 CSV 等）迁到 `workspace/datasets/`，沙箱内只读挂载到 `/datasets/`。net-ops persona 与 3 个 SKILL.md（fault-impact-analysis / ops-metrics-analysis / resource-capacity-analysis）数据集路径从裸文件名改为 `/datasets/...`。

### 新增

- **沙箱镜像构建文件**：`sandbox/image/Dockerfile` 基于 `python:3.12-slim` 预装 pandas / numpy / duckdb / matplotlib / openpyxl / python-docx / pyarrow / seaborn，与宿主 LocalShellBackend 数据分析栈能力对齐；不覆盖 entrypoint（保留 OpenSandbox SDK 默认 `tail -f /dev/null`，避免健康检查失败）

- **`run_python` 工具双路径执行**：沙箱模式下代码写入沙箱 `/tmp/_run_<rand>.py` → `cd /data && python3 ...` 执行；非沙箱模式保持原宿主机 subprocess 路径。三道护栏（20000 字符代码上限 / 6000 字符输出上限 / 120s 超时）始终生效

- **`backfill_sandbox_backend()` + `backfill_workspace_paths()` 启动钩子**：前者幂等把 net-ops 的 backend 字段对齐为 sandbox 并按特征句同步 persona 路径（管理员改过的 persona 不覆盖）；后者 best-effort 迁移老 uploads 目录结构与 netops CSV 到 datasets/（不删源、不阻断启动）

### 修复

- **DuckDB 文件位置规范化**：用户级 `uploaded_tables.duckdb` 从 uploads 子目录提到用户目录根下，沙箱内只读访问 uploads 时不必暴露 duckdb 文件（pandas 不需要，sql 工具走宿主侧 duckdb）

- **附件路径校验**：`validate_attachment_path` 与 fileqa `virtual_to_real` 同步新路径前缀 `/data/<uid>/uploads/`，防止路径伪造/穿越

### 验证

- pytest 全量回归通过（含 sandbox_mgr 14 项 + 新增 paths 迁移钩子单测）；未启用 SANDBOX_ENABLED 时 net-ops / biz-analyzer / xiaoshu 行为零变化；前端无改动，vite build 通过

### 已知限制

- 本版仅 net-ops 试点接入沙箱；xiaoshu / xiaoxiao / biz-analyzer 仍是 local_shell，后续独立 PR 铺开
- 真实沙箱联通需 OpenSandbox server 与 `sandbox/image/Dockerfile` 构建后的镜像，并配置 `[storage] allowed_host_paths` 放行 `SANDBOX_HOST_DATA` / `SANDBOX_HOST_DATASETS` 两个宿主机路径前缀
- 预热池、egress FQDN 白名单、生产 api_key 强制、孤儿沙箱清扫为二期优化项

***

## 0.12.0 (2026-09-09)

### 重磅变更：多模型可选 + 数据分析数据源权限体系（私有隔离 / 公共共享）

- **对话模型不再写死**：模型此前由员工 yaml 的 `${MODEL_NAME}` 环境变量唯一确定，对话页不可见也不可选。本版新增「模型管理」模块并打通全链路选择：**管理端配置多模型（含默认模型）→ 对话工作台/数据分析工作台顶栏下拉选择 → 请求体携带 → 会话级绑定 → 运行时按模型编译独立 agent（缓存键隔离）**。优先级：请求体 model > 会话绑定 model > 员工默认配置

- **数据分析数据源从「无鉴权全局共享」升级为「登录 + 私有隔离 + 公共共享」**：此前 `/api/analyst/*` 接口未登录即可访问，数据源详情接口会返回解密后的数据库明文密码，且所有用户共享全部数据源（owner_id 写入链路断裂形同虚设）。本版按「使用/管理」两级权限重构整个数据源权限体系

### 新增

- **模型管理（admin）**：catalog 库新增 `ai_models` 表（OpenAI 兼容协议，存供应商/base_url/加密 api_key），「系统设置 → 模型管理」页面 CRUD + 设默认模型；首次启动自动播种默认模型（读取 `.env` 的 `OPENAI_API_KEY`）；`GET /api/ai-models` 普通用户可访问（仅 LLM 类型，不含 api_key）；`resolve_runtime_model` 运行时按 DB 配置解析

- **对话页模型选择**：ChatView / AnalystView 顶栏模型下拉框（默认显示当前生效模型），切换员工重置默认、打开历史会话恢复绑定模型；`conversations` 表加 `model` 列（首条消息绑定，后续消息回退使用）；`runtime.get_agent(model_override)` 按 `\|m:{model}` 追加缓存键，不同模型编译独立 agent 互不污染

- **数据源私有隔离**：普通用户仅可见/可用**自己创建**的数据源；`owner_id` 修复为记录当前登录用户；创建/更新/删除/写标注全部加归属校验，越权统一 404 不暴露资源存在性

- **公共数据源（is_public）**：`datasources` 表加 `is_public` 列，迁移时把存量数据源统一标记为公共（保留升级前共享行为）；公共源对全员开放**使用**（下拉可选、问数连库、表结构/预览/标注只读），但**管理**（编辑配置/删除/改公共标记/写标注）仍限 owner 与管理员；`is_public` 仅管理员可设置，普通用户提交强制归零；前端列表显示「公共」徽标 + 管理员快捷开关，非可管理数据源显示「只读」并禁用编辑/删除/标注输入

- **运行时纵深校验**：streaming 注入数据源前做归属校验（越权不注入）；sql 工具层新增用户上下文 contextvar 二次校验，伪造 ds_id 绕过前端也会被拦截并记日志

### 修复

- **数据分析「数据源不存在」**：前端回传 JSON 格式 `{"kind":"database","id":"ds:ds_xxx"}` 时 `parse_data_source` 未剥 `ds:/kb:/conn:` 前缀，导致注入双前缀 ID 查库必然失败（此前表现为数字员工提示"数据源失效需重新选择"，实际数据源一直在库中）；同时 `_resolve_datasource_id` 改为会话注入（用户 UI 选择）优先于 LLM 传值，防止 LLM 从历史消息捞到陈旧/已删除数据源 ID 覆盖当前选择

- **数据源接口鉴权缺失**：`/api/analyst` 整组路由补登录依赖（未登录从 200 → 401）；详情接口不再返回明文密码（脱敏 `***`，编辑保存时后端回填原密码，测试连接密码回填仅限可管理者）

- **审计日志页贴边**：`.audit-page` 缺 padding 导致内容顶格，补齐与系统设置其他页一致的边距规范（18px 28px 24px）+ 自身滚动

### 验证

- analyst 专项 153 项 + 核心 80 项测试全通过；未登录访问 analyst 接口全部 401；跨用户脚本实测私有隔离/公共源可见性/只读约束；前端构建通过

***

## 0.10.0 (2026-09-04)

### 重磅变更：数字员工从「被动问答」升级为「主动执行」——自动化任务平台

- **补上机器触发这半边**：平台此前所有对话 run 均由人发消息发起，定时简报、到期提醒、预警维系这类高价值场景天然无法覆盖。本版新增「自动化任务」子系统：**定时（cron）/ 事件（webhook）两类触发源 → 自动起 run → 结果落会话（可选推送外部 IM）**，数字员工开始具备"到点主动干活、事件来了自动响应"的产品形态

- **执行链路完全复用对话运行时**：自动 run 与人工对话走同一条 `_stream_run` 链路——敏感词护栏、工具调用护栏、长期记忆、Trace 全链路可观测、审批中断全部生效；每次触发的结果都是一条完整会话，在会话历史中可见、可回溯、可继续追问，而非黑盒日志

- **三大典型场景开箱即用**：

  - 每日经营简报——`0 9 * * 1-5` 定时让 xiaoshu 拉数出简报，结果推送到 IM 频道

  - 合同/到期提醒——定时扫描本体数据，到期前自动生成维系建议

  - 事件驱动处理——CRM 退款、监控告警等外部系统 webhook 一发，客服/运维员工立即产出处理方案（如需外发可接审批）

### 新增

- **定时任务（cron）**：`automations` 表 + 调度器随应用 lifespan 启动（30s 扫描周期）；`next_fire_at` CAS 抢占保证多实例/慢执行重入时同一触发点只执行一次；停机期间错过的触发点只补跑一次，不追历史风暴；`AUTOMATIONS_DISABLED=1` 可关闭

- **事件触发（webhook）**：`POST /api/automations/events/{event_key}` 即时触发所有监听该事件的任务；任务级 secret 鉴权（未配置则放行）；事件数据 JSON 自动注入指令模板 `{{payload}}` 占位符（无占位符时附加尾部），`{{now}}` 注入当前时间；同步返回每个任务的执行结果（会话 ID + 完整回复）

- **前端「自动任务」管理页**（admin，侧边栏）：任务列表（触发方式/员工/指令/上次运行状态与次数/失败原因提示）、启停开关、新建编辑弹窗（cron 快捷模板、事件调用地址展示、员工/频道下拉）、「立即运行」手动验收并直接查看 agent 回复

- **结果推送**：任务可绑定 IM 频道，执行结果经频道 `outbound_webhook` 推送到企业微信/飞书等外部 IM；不绑定则静默落会话历史

- **零新增依赖的 cron 解析器**：自实现 5 字段解析（支持 `*` `,` `-` `/`、`7=周日`、日/周同时受限取并集的标准语义），创建/编辑时校验表达式合法性并预排 `next_fire_at`

- **回归测试 tests/test\_automations.py（19 条全通过）**：cron 匹配/next\_fire 计算/非法表达式/CAS 抢占防重/CRUD/启停重排期/模板渲染

### 修复

- traces 聚合 SQL 的 PostgreSQL 方言 bug：`SUM(etype='llm')` 布尔求和写法在 PG 报 `function sum(boolean) does not exist`，导致每次 run 的 llm\_calls/tool\_calls 统计回写失败、trace 卡在 running；改为 `SUM(CASE WHEN ... THEN 1 ELSE 0 END)`（SQLite/PG 双方言兼容）

***

## 0.9.0 (2026-09-01)

### 重磅变更：新增「浙江联通售前客服」，移除旧演示客服 xiaosu

- **新员工 unicom-presale（小联·浙江联通售前客服）**：售前咨询人设（资费/政策/流程必须先 kb\_search 检索、禁止编造），绑定 RAGFlow「浙江联通业务知识库」，工具 kb\_search + create\_ticket

- **新技能 unicom-presale-faq**：浙江联通售前咨询规程（定位主题 → 检索 → 引用来源 → 给下一步建议）

- **RAGFlow「浙江联通业务知识库」**：联网搜集整理的 11 个知识文档（5G 套餐、融合宽带、互联网卡、特色套餐、携号转网、合约变更、靓号、销户异地、话费积分、政企业务、增值国际业务），101 chunks，配套幂等灌入脚本 `scripts/seed_zj_unicom.py`

- **移除 xiaosu（旧演示客服）**：员工 yaml、product-faq / complaint-handling 技能、sop\_complaint 种子及 catalog 记录全部清理，历史会话数据保留；依赖真实种子员工的测试改用 unicom-presale

### 变更

- 调试端点（/api/debug/memory、runtime.dump\_store）默认员工从 xiaosu 改为 unicom-presale

- CONNECTOR\_ASSIGN 中 crm 连接器指派移除 xiaosu；本体工具 backfill 名单加入 unicom-presale

***

## 0.8.0 (2026-08-30)

### 重磅变更：net-ops 从「单技能」升级为「算网运营专家」四能力架构

- **net-ops 人设与能力完整升级**：角色改为「算网运营专家」，backend=local\_shell，4 项核心技能 + 3 条算网专用 SOP 绑定；内置员工保持 6 个，但小网已从 1 个技能 → 4 技能满配

  - **故障影响分析**：告警关联（netops\_alerts.csv 按基站/时间窗/严重度统计）+ 本体多跳（基站 → cover 片区 → 客户 → 筛 VIP → 装维责任人 → 联系方式）

  - **运营指标分析**：趋势/环比/同比 + SLA 达标判定 + 异常日定位与告警归因（联动网元表定位具体故障场景）

  - **资源容量分析**：算力 / 网络 / IDC 三类台账跑数 + 80% 预警/90% 紧急扩容阈值 + 目标 70% 扩容缺口公式 + 本体 deploy\_in/backhaul 归属查询

  - **SOP 路由与执行**：按场景路由到 cutover/emergency/escalation → 刚性步骤逐条执行 → create\_ticket 登记工单 → /memories/ 沉淀处置经验

### 新增

- **三条算网 SOP 制度（catalog seeds + Store 接入）**：

  - sop\_netops\_emergency 算网应急预案启动（5 步：影响面判定 → 分级 → 通知链 → VIP 保障 → 工单登记）

  - sop\_netops\_cutover 网络割接操作规范（6 步：申请 → 影响评估 → 00:00-06:00 时间窗刚性 → 超 90 分钟强制回退 → 执行监控 → 完工）

  - sop\_netops\_escalation 重大故障升级上报（5 步：P1 判定 → 15 分钟到值班长、30 分钟首次升级 → 升级链路 → 工单 → 跟进）

- **老库幂等升级 backfill\_netops\_upgrade()**：三路径互不干扰——SOP 按 slug 幂等补缺；员工-技能/员工-SOP 绑定按 emp\_id+skill\_id(sop\_id) 幂等补缺；persona/description 仅在"管理员未改动"的情况下才覆盖升级，保护自定义修改

- **本体扩展：算网资源域**：新增实体类型 机房(datacenter)/算力节点(compute\_node)/传输链路(link)，关系类型 部署于(deploy\_in)/回传链路(backhaul)；种子播种 2 机房、4 算力节点、3 传输链路 + 4 条 deploy\_in + 4 条 backhaul 关系，与本体已有基站/片区可直接组合多跳查询；函数 `seed_netops_resources_if_empty()` 幂等

- **三份算网演示数据集 + 生成脚本**（scripts/generate\_netops\_data.py，固定随机种子可复现）：

  - netops\_alerts.csv：378 条告警（90 天），P1-P4 四档，埋三条故事线：城东 8/8-8/10 连续 P1 板卡故障、高新 2 号站近 30 天 P2 传输故障频发、周末突发故障

  - netops\_kpi.csv：181 天 × 3 片区的接通率/掉线率/SLA/满意度，KPI 与城东大障日同步跌落

  - netops\_resources.csv：12 条三类资源台账，GPU 训练节点 92.2% + 高新-下沙光缆 87.0% 命中预警

- **专项回归测试 tests/test\_netops\_expert.py（10 条全通过）**：覆盖数据结构/故事线/yaml/触发条件/SOP 播种/backfill 双路径（空库/老库）/本体幂等；pytest 夹具 `tmp_db` 保证 SQLite 不碰真实数据

- **E2E 手动验证脚本 scripts/verify\_netops\_e2e.py**：4 个典型问题 HTTP API 直跑（登录→改密→会话→SSE 流），自动核对工具调用与回答要点，便于改动后的冒烟

### 优化

- README 与 .env.example 中 APP\_VERSION 示例值从历史遗留的 0.4.0/0.6.0 统一追平到 0.8.0

***

## 0.5.0 (2026-08-27)

### 新增

- **MCP 连接器支持 HTTP transport**（#12）：连接器配置 `transport: "http"`（或 `streamable-http` / `streamable_http`）归一化为 Streamable HTTP 接入，url 原样透传；资源中心可直接接入远程 HTTP 型 MCP server（如 scrapling），无需本地子进程。stdio 行为不变

- **网络运营数字员工「小网」**（#10）：内置员工增至 6 个，网络运营专家岗位打样——故障影响分析技能（基站退服 → 覆盖片区 → 受影响客户 → 筛 VIP → 装维责任人 → 登记工单），完整展示企业本体多跳关系查询能力

- **本体扩展：网络运营领域**（#10）：新增实体类型 基站(station) / 片区(area)，关系类型 覆盖(cover) / 维护(maintain) / 居住于(located\_in)；网络运营演示数据「星联通信」（1 组织 / 4 员工 / 4 基站 / 3 片区 / 5 客户），含退服基站 BS-003 场景

- **本体老库平滑升级**（#10）：`backfill_schema_types()` 幂等补齐新增预置类型；`backfill_employees_if_missing()` 幂等补种新内置员工（含技能/工具/授权），已有库无需清库重建

- **本体关系图谱**（#7）：本体页新增「关系图谱」tab，echarts 力导向布局——实体为节点、关系为连线，按实体类型着色 + 图例过滤、连线显示中文关系名、节点大小随关联数变化、悬停高亮邻接、点击节点打开详情、可拖拽/缩放/重新布局

### 优化

- 本体全面中文化显示（#6）：业务关系表格、实体详情、类型定义、下拉选择等处统一显示类型中文名（悬停保留 code），未定义中文名时回退 code

- 类型定义支持编辑保存（#7）：修复编辑弹窗只调创建接口（POST）导致"code 已存在"报错的 bug，编辑走 PUT

### 修复

- 表格 render 函数内按钮改用真实组件对象渲染（#9）：修复本体页操作列按钮无手型光标、无样式、间距挤的问题；编辑/删除按钮配色与间距同会话历史页风格统一（编辑主题蓝、删除红色）

- 类型系统放开预置类型只读限制（#8）：预置实体/关系类型可编辑与软删除（code 仍不可改），配合演示数据场景灵活调整

- 中文 README 移除残留的英文简介段落，双语同步 net-ops 员工信息（#11）

***

## 0.4.0 (2026-08-27)

### 重磅变更：数据库迁移 PostgreSQL

- **存储后端由 SQLite 整体切换为 PostgreSQL**（#3）：面向多用户并发与网络访问的企业共享部署场景，SQLite 单写锁不再适用

- 新增 `app/db.py` 双方言数据访问层：psycopg 连接池 + SQL 方言翻译（`INSERT OR IGNORE→ON CONFLICT`、`AUTOINCREMENT→IDENTITY`、`?→%s`），业务代码保持统一写法；`DB_BACKEND=sqlite` 分支仅测试夹具使用

- checkpointer / store 切换为官方 `langgraph-checkpoint-postgres`（`AsyncPostgresSaver` / `AsyncPostgresStore`），`streaming.py` 启动恢复兼容 PG 表结构

- catalog / conversations / traces / approvals / ontology 全部接入访问层；修复 users 主键秒级时间戳碰撞问题

- `docker-compose.yml` 新增 `db` 服务（postgres:16-alpine，首启自动建 7 个业务库）；新增 `scripts/init_postgres.sql` 与幂等建库脚本 `scripts/init_postgres.sh`（支持 `--host/--port/--prefix`）

- `backup.sh` 改用 `pg_dump`（支持 `PGBIN` 指定路径）；requirements 增补 psycopg / checkpoint-postgres

- **升级注意**：`DB_BACKEND=postgres` + `POSTGRES_*` 环境变量必填（见 `.env.example`），存量 SQLite 数据需自行迁入

### 新增

- 运行评估功能：每条回答 👍/👎 反馈（含点踩原因浮层），管理员评估仪表盘（指标卡片 + 日趋势 + Top 工具 + 反馈明细，`AdminEvaluation.vue`）；SSE 新增 `message_end` 事件携带反馈关联 ID

- 对话附件上传：`/api/conversations/{id}/attachments`（单文件 20MB 限制），附件路径注入消息文本，前端输入栏支持附件选择与消息内附件标签

- 运行 / 工具错误在对话页可见化，用户不再只看到静默失败

- 前端聊天视图组件化：ChatView 拆分为 InputBar / ChatMessage / PipelineSidebar / ConversationSidebar / ReasonPopover

- 开源就绪：CI（后端 pytest + 前端构建）、issue 模板、PR 模板、CODE\_OF\_CONDUCT / SECURITY / CONTRIBUTING 社区文件

- 英文 README（`README.en.md`），中英双语切换；LICENSE 修复为标准 MIT 全文，GitHub 正确识别

### 修复

- 过滤 `content` 内联思考标签，防止污染会话标题生成与历史消息展示（#2）

- 恢复消息评价按钮——聊天视图组件拆分时遗漏了 `message_end` 事件处理导致 `run_id` 为空

- 可靠性修复：文档工具数据按用户隔离、trace 写入失败可观测（不再静默吞错）、退款审批双路径补充测试

- 修复全新环境启动与退款审批路径的 bug（开源前回归）

***

## 0.3.1 (2026-08-04)

### 新增

- 技能动态 Store 同步：新增 `runtime.sync_skills_to_store()`，`get_agent()` 编译前会把当前员工技能内容接入 Store

- 新增 `PUT /admin/skills/{skill_id}/content` 接口：直接保存自定义技能 SKILL.md 内容

- 技能 zip 上传/内容变更后只刷新 Store，不再触发 agent 重编译

- 前端技能编辑弹窗支持直接修改 SKILL.md 内容保存（未选择 zip 且编辑自定义技能时）

- 新增 `runtime.refresh_skills_for_employees()`，技能变更统一刷新受影响员工

- `run_python` 增加代码长度 / 输出大小资源限制，默认 20000 字符输入、6000 字符输出，可环境变量覆盖

- 技能 Store 命名空间按用户隔离：`/skills/` 路由从 `(emp_id)` 调整为 `(user_id or "default", emp_id)`，不同用户视角的技能集合互不覆盖

- 临时提供 `MCP_DISABLED=1` 启动开关，MCP stdio 初始化失败时不再拖垮服务

- IM 频道第一批（Web）：新增 `/api/im/*` 频道接口，启动时自动创建“全员频道”，频道内可选择数字员工、查看会话历史、SSE 流式回复

- 前端 `/app/im` 从占位页替换为 `ImView.vue`，左侧频道列表 + 会话列表 + 聊天区，并复用现有 SSE Markdown / 工具 trace / 审批卡片渲染

### 修复

- 修复技能运行时无法感知 SKILL.md 内容变更的问题

- 修复前端技能编辑弹窗 `openModal` 使用 `await` 但函数未声明 `async` 的编译错误

- 技能路由保持轻量摘要：SKILL.md 全文不进入 system\_prompt，详细规程通过 Store/read\_file 运行时读取（新增契约测试）

- 清理 `tools/kb.py` 死代码 `kb_search`，运行时统一使用 `compiler.make_kb_search` 闭包

- 新增 `runtime.refresh_skills()` 统一技能刷新入口；用户覆盖变化只刷新用户技能视图并清用户变体缓存

- `kb_search` 改为运行时动态查询 catalog，知识库条目不再作为编译期快照固化进工具闭包

- 知识库条目 add/edit/delete 不再触发 agent 重编译，运行时 `kb_search` 自动读取最新条目

- SOP 动态加载：`/sops/` Store 路由 + `sync_sops_to_store()`，SOP 全文不再拼进 system\_prompt，编辑 SOP 后只刷新 Store

- SSE 错误分级：`_stream_run` 异常不再把内部异常文本直接返回前端，改为稳定 `error_code` + 通用提示

- `reconstruct()` 并行工具调用结果不再按顺序错配，改为优先按 `tool_call_id` 精确匹配（结果乱序时也能对应正确的工具调用）

- `recover_conversations()` 增加启动恢复条数上限，默认 `CONV_RECOVER_LIMIT=2000`，避免启动全表扫描

- `employee_of()` 在员工目录为空时不再抛 `IndexError`，返回明确 SSE 错误提示

- 审批中心从内存版改为 SQLite 落库（`approvals.db`）：生效 `APPROVAL_TTL_SECONDS` 过期自动拒绝、`APPROVAL_PENDING_LIMIT` pending 数量上限

- 新增 `runtime.shutdown_mcp()`：应用退出时统一关闭 MCP client（优先 `aclose`，回退 `__aexit__`），避免 stdio 子进程残留

- 前端 SSE 流式请求增加 `AbortController`：页面卸载或发起新请求时中断旧连接，避免服务端挂起时连接不释放

- `.dockerignore` 补全 `frontend/dist/`、`.pytest_cache/` 等缓存目录，镜像构建上下文更干净

- 确认强制改密 API 层拦截已生效：`must_change_password=true` 的用户只能访问登录/改密/当前用户接口，其余 `/api` 返回 403

- 修复管理后台点击左侧菜单整页闪一下的问题：`/app` 子路由不再重建 `MainLayout`，左侧栏保持稳定，内容区独立淡入淡出

### 技术债

- 待办新增 `P6 核心能力动态化（技能 / 知识库 / SOP / MCP）`，用于持续推进“编译期固化”改为“运行时可读取/可分配”

***

## 0.3.0 (2026-07-26)

### 重构

- 移动 5 个 SQLite 数据库从根目录到 `data/db/`，`paths.py` 默认路径同步更新

- 删除废弃的 `app/static/` HTML 文件（已被 `frontend/src/` Vue 前端替代）

- 所有 `.vue`/`.js` 文件顶部加中文文件说明，`__init__.py` 补充包说明

### 新增

- 前端可复用分页组件 `PaginationBar.vue`

- 知识库条目详情弹窗（查看完整内容）

- SOP 展开/收起全文

- 技能内容查看弹窗（SKILL.md 全文）

- 技能编辑弹窗新增 SKILL.md 内容字段

- 公共知识库条目只读接口 `GET /api/knowledge-bases/{id}/entries`

- `pyproject.toml` 项目元数据文件

- `CLAUDE.md`、`TODO.md` 项目文档

### 修复

- 前端路由跳转全部改为按 name 跳转，解决绝对路径不匹配子路由的问题

- 左侧菜单切换闪烁（移除 transition + 改用 keep-alive 缓存组件）

- ChatView 缺失 `useRouter` 导入导致"执行过程"按钮无反应

- HistoryView 缺失 `reactive` 导入导致页面空白

- 资源中心知识库条目 API 路径 `/admin/kbs/` → `/admin/knowledge-bases/`

- 资源中心普通用户无法查看知识库条目（后端新增公共 API）

- Trace 默认折叠（traceExpanded: true → false）

- "执行过程"链接从 `<a href="/trace">` 改为 `router.resolve`

- $router.push('/history') 改为 `{name:'history'}`

### 丰富

- FAQ 知识库从 6 条扩展到 30 条（5 产品线 + 通用政策）

- MOCK\_ORDERS 从 3 个扩展到 10 个

- CRM 客户从 2 个扩展到 6 个

- 销售数据集从 2 产品 × 24 行扩展到 5 产品 × 60 行

- SOP 内容全部重写为完整版本

- product-faq / complaint-handling 技能文档扩充

- 小苏 / 小数人设扩充

### 管理后台

- 资源中心对普通用户可见（只读，admin 有全部 CRUD 权限）

- 员工管理 + 用户管理插入主导航（仅 admin 可见）

- 首页统计修复（并行调用 /employees + /catalog + /conversations）

***

## 0.2.0 (2026-07-24)

### 新增

- 前端 Vue 3 + Vite + Naive UI 重构

- 对话 SSE 流式响应

- HITL 审批决策

- 执行过程追踪（traces）

- 用户 - 员工分配机制

- 资源中心（技能/工具/知识库/SOP/连接器 CRUD）

### 修复

- 软删除各实体级联关系

- 登录限流

- XSS 消毒

***

## 0.1.0 (2026-07-22)

首次提交：myagents 数字员工平台初始代码。
基于 deepagents + LangGraph 的数字员工运行平台，含小苏（客服）和小数（数据分析师）两个员工模板。
