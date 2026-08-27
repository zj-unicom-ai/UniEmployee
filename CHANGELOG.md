# Changelog

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
- 开源就绪：CI（后端 pytest + 前端构建）、issue 模板、PR 模板、CODE_OF_CONDUCT / SECURITY / CONTRIBUTING 社区文件
- 英文 README（`README.en.md`），中英双语切换；LICENSE 修复为标准 MIT 全文，GitHub 正确识别

### 修复

- 过滤 `content` 内联思考标签，防止污染会话标题生成与历史消息展示（#2）
- 恢复消息评价按钮——聊天视图组件拆分时遗漏了 `message_end` 事件处理导致 `run_id` 为空
- 可靠性修复：文档工具数据按用户隔离、trace 写入失败可观测（不再静默吞错）、退款审批双路径补充测试
- 修复全新环境启动与退款审批路径的 bug（开源前回归）

---

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
- 技能路由保持轻量摘要：SKILL.md 全文不进入 system_prompt，详细规程通过 Store/read_file 运行时读取（新增契约测试）
- 清理 `tools/kb.py` 死代码 `kb_search`，运行时统一使用 `compiler.make_kb_search` 闭包
- 新增 `runtime.refresh_skills()` 统一技能刷新入口；用户覆盖变化只刷新用户技能视图并清用户变体缓存
- `kb_search` 改为运行时动态查询 catalog，知识库条目不再作为编译期快照固化进工具闭包
- 知识库条目 add/edit/delete 不再触发 agent 重编译，运行时 `kb_search` 自动读取最新条目
- SOP 动态加载：`/sops/` Store 路由 + `sync_sops_to_store()`，SOP 全文不再拼进 system_prompt，编辑 SOP 后只刷新 Store
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

---

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
- MOCK_ORDERS 从 3 个扩展到 10 个
- CRM 客户从 2 个扩展到 6 个
- 销售数据集从 2 产品 × 24 行扩展到 5 产品 × 60 行
- SOP 内容全部重写为完整版本
- product-faq / complaint-handling 技能文档扩充
- 小苏 / 小数人设扩充

### 管理后台
- 资源中心对普通用户可见（只读，admin 有全部 CRUD 权限）
- 员工管理 + 用户管理插入主导航（仅 admin 可见）
- 首页统计修复（并行调用 /employees + /catalog + /conversations）

---

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

---

## 0.1.0 (2026-07-22)

首次提交：myagents 数字员工平台初始代码。
基于 deepagents + LangGraph 的数字员工运行平台，含小苏（客服）和小数（数据分析师）两个员工模板。
