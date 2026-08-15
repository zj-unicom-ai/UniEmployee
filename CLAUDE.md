# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 架构

**UniEmployee 数字员工平台** —— 基于 **deepagents 0.6.12** (LangGraph 1.2.9) 的多租户数字员工运行平台。

五层能力模型：`Employee → Workflow/SOP → Skill → Connector → Tool`

### 项目分层

```
backend/                     # 后端（Python FastAPI）
├── app/
│   ├── main.py              # ★ 网关：SSE 流式对话 / 审批恢复 / 鉴权 / admin CRUD / 前端静态挂载
│   ├── compiler.py           # ★ 编译层：EmployeeSpec → create_deep_agent()
│   │   ├── ALL_LOCAL_TOOLS   #   全量本地工具注册表（dict）
│   │   ├── _assemble_tools() #   按 spec 装配工具（本地 + MCP + 通用工具）
│   │   └── compile_agent()   #   主入口：skill 播种→工具装配→system_prompt→create_deep_agent
│   ├── runtime.py            # agent 缓存 / checkpointer / store / 预热 / 失效
│   ├── spec.py               # EmployeeSpec Pydantic 模型 + load_spec(yaml)
│   ├── catalog.py            # catalog.db（员工 / 技能 / 工具 / 知识库 / SOP / 连接器 CRUD + 用户管理）
│   ├── auth.py               # bcrypt + JWT + FastAPI 鉴权依赖（get_current_user / get_admin_user）
│   ├── approvals.py          # HITL 审批单（内存版）
│   ├── conversations.py      # 会话元数据 conversations.db
│   ├── traces.py             # Trace 追踪 + TraceHandler(AsyncCallbackHandler)
│   ├── errors.py             # 全局异常处理 → 干净 JSON 500
│   ├── paths.py              # 统一数据目录 DB 路径（APP_DATA_DIR 控制）
│   ├── logging_setup.py      # 结构化日志 + 请求ID
│   ├── tools/                # Tool 实现
│   │   ├── kb.py             #   kb_search(旧版关键词+闭包), create_ticket
│   │   ├── data_tools.py     #   run_python（pandas/matplotlib），get_my_id
│   │   ├── search.py         #   bocha_search（联网搜索）
│   │   ├── time_tools.py     #   get_current_time
│   │   ├── wiki_tools.py     #   query_product_wiki, list_product_catalog
│   │   └── doc_tools.py      #   generate_solution_doc（Word 方案文档生成，python-docx）
│   ├── workflows/
│   │   └── refund.py         # 退款 StateGraph（内化审批：validate→calc→await_approval→execute）
│   └── connectors/
│       └── crm_server.py     # CRM FastMCP stdio server（mock）
├── employees/*.yaml          # 员工种子定义（仅首次启动写入 catalog.db）
├── skills/                   # 内置技能（各含 SKILL.md + frontmatter）
├── pyproject.toml            # Python 项目元数据 + pip 依赖
├── requirements.txt          # 精简依赖（指向 requirements.lock.txt）
└── Dockerfile

frontend/                     # Vue 3 + Vite + Naive UI + Pinia + Vue Router
├── src/views/                # LandingView, LoginView, ChatView, HistoryView, TraceView,
│                               AdminView, UsersView, HomeView, ResourcesView, CasesView,
│                               CaseDetailView, ChangePasswordView
├── src/api.js                # Axios 封装（自动注入 Bearer token + 401 跳转）
├── src/router/index.js       # 路由：/ → landing, /login, /app/{home,chat,history,admin,...}
├── src/stores/auth.js        # Pinia 认证状态
├── src/layouts/MainLayout.vue # 管理后台主布局（侧栏导航 + 右侧内容区）
└── dist/                     # Vite 构建产物（FastAPI 挂载为静态文件）

tests/                        # pytest（在项目根目录运行，不 backend/ 下）
├── conftest.py               # tmp_db 夹具：临时 SQLite 库，不碰真实数据
└── test_*.py                 # pytest -q 自动发现

.docs/                        # 参考文档（deepagents 官方文档、架构设计）
skills-custom/                # 用户上传的自定义技能（gitignore），含 pdf/、pptx/ 等
data/db/                      # 5 个 SQLite 库运行时目录
scripts/backup.sh             # 数据库备份脚本
workspace/                    # 数据分析看板输出（按用户隔离）
```

### SQLite 数据库（5 个，均在 `data/db/` 或 `$APP_DATA_DIR`）

| 文件 | 作用 |
|------|------|
| `catalog.db` | 员工/技能/工具/知识库/SOP/连接器/用户/分配（CRUD 全在 catalog.py） |
| `conversations.db` | 会话元数据（标题/预览/归属/计数/软删） |
| `checkpoints.db` | LangGraph checkpointer（对话状态/消息历史，SqliteSaver） |
| `store.db` | 长期记忆（AsyncSqliteStore，按 user+员工隔离，重启不丢） |
| `traces.db` | 执行过程追踪（runs + events，TraceHandler 异步写入） |

### 核心数据流

```
用户消息 → POST /api/conversations/{id}/messages → SSE 流
  → runtime.get_agent(emp_id, user_id, overrides)
    → catalog.get_employee_config() 读取可选配置
    → compile_agent() 编译（缓存中有则跳过）
  → agent.astream(input, config, stream_mode=["updates","messages"])
    → "messages" 模式: AIMessageChunk(token) → SSE type:token
    → "updates" 模式: 节点状态规划/工具/技能/中断 → SSE type:thinking/tool/approval_required/todos/stage
  → traces.TraceHandler 捕获 LLM/工具回调 → traces.db（运行不阻塞）
  → __interrupt__ 到达 → approvals.create() → SSE type:approval_required
  → 审批人调用 POST /api/approvals/{id}/decision → Command(resume=...) 恢复
```

### 技能路由机制

1. 编译期 `compile_agent()` 把技能内容播种进 Store `namespace=(spec.id,)`
2. `_build_skill_routing()` 从 SKILL.md 提取触发条件 → 拼进 system_prompt 的"技能路由"节
3. `create_deep_agent(skills=["/skills/"])` 挂载 StoreBackend
4. 运行时模型通过 `read_file` 查阅完整规程，不能凭记忆跳过

### 记忆隔离

- CompositeBackend: 默认后端 + `/memories/` → StoreBackend `namespace=(user_id, emp_id)` + `/skills/` → StoreBackend `namespace=(spec.id,)`
- 记忆在编译期通过 `memory_namespace(user_id, emp_id)` 闭包捕获
- `ensure_user_memory()` 在首次对话时懒播种 AGENTS.md 模板

### 用户覆盖机制

- 模板配置（admin 设置）+ 每用户 add/remove 覆盖（通过 `user_employee_assignments` 表）
- 缓存键：admin → `emp_id`，普通用户 → `f"{emp_id}|{user_id}"`
- `get_effective_config()` 合并：`base ∪ add − remove`

### 审批双路径

- 轻量审批（create_ticket）：外层 agent 的 `interrupt_on` 拦截 → `allowed_decisions: [approve, reject]`
- 退款审批（Point2 内化）：refund StateGraph 内 `await_approval` 节点 `interrupt()` → 内层 thread `refund:{order_id}:{hash}` 隔离 → decision 端点先 `resume_refund()` 恢复内层图，再用 `Command(resume=summary)` 恢复外层 agent

## 开发命令

```bash
# 运行服务（PYTHONPATH 指向 backend）
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --port 8787 --reload

# 前端开发
cd frontend && npx vite

# 前端构建
cd frontend && npx vite build

# 运行全部测试
.venv/bin/python -m pytest tests/ -v

# 运行单个测试文件
.venv/bin/python -m pytest tests/test_catalog.py -v

# 运行单个测试用例
.venv/bin/python -m pytest tests/test_catalog.py::test_name -v

# 安装依赖
.venv/bin/pip install -r backend/requirements.txt

# 容器构建并运行
docker compose up -d --build

# 健康检查
curl http://localhost:8787/health

# 备份 5 个数据库
./scripts/backup.sh
```

### 测试约定
- `tests/conftest.py` 的 `tmp_db` 夹具（autouse）自动把 catalog.db / conversations.db 替换为临时 SQLite 文件
- 测试不碰真实数据库文件
- 默认 `pytest -q`；慢测试（联网/浏览器）标记 `@pytest.mark.slow`（定义在 `pyproject.toml` + `pytest.ini`）
- 测试在项目根目录运行（非 `backend/` 下）

## 员工管理

### 添加新员工
1. 创建 `backend/employees/<id>.yaml`（人设、模型、技能列表、工具列表、MCP 配置、中断策略）
2. 在 `catalog.py seed_if_empty()` 的 `seeds` dict 里注册初始选中项（skills/tools/kbs/sops/cons）
3. 若有自定义工具，在 `compiler.py ALL_LOCAL_TOOLS` 注册
4. 若有新 MCP 连接器：Python 型在 `connectors/` 下创建 FastMCP stdio server（command 用 `${PYTHON_BIN}`）；node/npx 型直接在连接器 config 里写 `command: npx` + `args` + `env`（`${PYTHON_BIN}` 之外的 command 会被原样透传给 MCP client，见 `compiler._assemble_tools`）。新增连接器统一登记进 `seeds.py CONNECTOR_SEEDS`（新库）+ `CONNECTOR_ASSIGN`（指派员工），旧库靠 `backfill_connectors()` 幂等补缺
5. 若有新 workflow，在 `workflows/` 下创建 StateGraph
6. 重启服务 → 自动种子进 catalog.db，`runtime.warmup_all()` 预热编译

### 现有员工（backend/employees/*.yaml）
- `xiaosu.yaml` — 客服
- `xiaoshu.yaml` — 数据分析师
- `xiaoxiao.yaml` — 销售
- `hrbp.yaml` — HR 合作伙伴

### 内置技能（backend/skills/）
- `product-faq/` — 产品 FAQ 查询
- `complaint-handling/` — 投诉处理规程
- `data-analysis/` — 数据分析
- `frontend-design/` — 前端设计指导
- `enterprise-sales/` — 企业销售
- `hr-assistant/` — HR 助手

均含 frontmatter（`name`/`description`）+ `## 触发条件` 段落，前端管理后台可见内容。

## 添加新工具
1. 在 `backend/app/tools/` 下用 `@tool` 装饰器定义
2. 在 `compiler.py` 的 `ALL_LOCAL_TOOLS` dict 里注册
3. 员工在 catalog.db 的 `tools` 表里选择该工具（页面配置或种子数据）

### 当前注册的工具（ALL_LOCAL_TOOLS，compiler.py）
- `create_ticket` — 创建工单
- `bocha_search` — 博查网搜索
- `get_my_id` — 获取当前用户 ID
- `get_current_time` — 获取当前时间
- `query_product_wiki` — 查询产品百科
- `list_product_catalog` — 列出产品目录
- `start_refund` — 启动退款流程（工厂函数，需运行时注入 checkpointer，不在 ALL_LOCAL_TOOLS 表）

## 设计理念

- **深度模块**：compiler.py 是核心深度模块——表面是 `compile_agent()` 一个异步函数，内部做技能播种、工具装配、system_prompt 拼接、CompositeBackend 路由、MCP client 拉起
- **运行时以 catalog.db 为准**：employees/*.yaml 仅作种子源，页面化配置后运行时全从库读
- **Trace 不影响主流程**：所有写 traces.db 均吞异常
- **用户级记忆隔离**：compile_agent 编译期闭包捕获 user_id，避免运行时 get_config() 不可用问题
- **审批内化**：refund StateGraph 的 await_approval 节点用 interrupt() 原语挂起，不依赖外层 agent 的 interrupt_on 拦截