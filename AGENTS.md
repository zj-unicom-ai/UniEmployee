# AGENTS.md

UniEmployee 数字员工平台（deepagents 0.7.5 / LangGraph 1.2.9 / FastAPI / Vue 3）。中文交流。

## 这个项目能做什么

- **数字员工构建与运行**：人设/模型/技能/工具/知识库/SOP/连接器全部页面化配置，运行时从 `catalog.db` 读取。内置 5 个员工：`xiaosu`(客服)、`xiaoshu`(数据分析)、`xiaoxiao`(销售)、`hrbp`(HR)、`biz-analyzer`(小经·经营分析，含子代理市场调研)。
- **流程技能与 SOP**：`SKILL.md` 规程沉淀（含触发条件），播种进 Store 供模型运行时 `read_file` 查阅；关键流程用 StateGraph 状态机固化（退款流程内化人工审批节点）。
- **知识检索**：FAQ 知识库（关键词+闭包）、markdown 产品 Wiki、RAGFlow 向量检索多源；回答标注来源。
- **连接器与工具**：MCP 标准接入（CRM stdio、newsnow npx）；内置工单/搜索/文档生成/数据分析等原子工具。
- **人机协同**：HITL 人工审批（轻量工单审批 + 退款流程内化审批双路径），跨会话长期记忆（按 user+员工隔离落盘 store.db），全链路 Trace 可观测，IM 频道扩展架构（`/api/im/*`，当前 Web 已实现）。

## 开发命令

```bash
# 后端（必须 PYTHONPATH=backend，.env 在项目根，启动时 dotenv 加载）
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --port 8787 --reload

# 前端 dev / build（构建产物 dist/ 由 FastAPI 静态挂载）
cd frontend && npx vite          # 或 npx vite build

# 测试：必须在项目根目录跑（不要进 backend/），依赖 PYTHONPATH
PYTHONPATH=backend .venv/bin/python -m pytest tests/test_catalog.py::test_name -v
PYTHONPATH=backend .venv/bin/python -m pytest tests/ -v

docker compose up -d --build     # 容器部署（.env 注入，data/db 挂载）
curl http://localhost:8787/health
./scripts/backup.sh              # 备份全部 SQLite（清单来自 paths.py DB_FILES）
```

- 仓库**未配置任何 lint/typecheck**（无 ruff/eslint/mypy/pre-commit）。改完代码用 pytest 自检，无对应测试文件的改动至少保证 `pytest tests/ -q` 通过。
- 慢测试（联网/浏览器）标记 `@pytest.mark.slow`，默认跳过。测试用 `tests/conftest.py` 的 `tmp_db` autouse 夹具把 catalog/conversations/approvals 库替换为临时文件，不碰真实数据。
- 首次运行需 `cp .env.example .env` 填 `OPENAI_API_KEY`/`JWT_SECRET` 等。默认 admin/admin123，首登强制改密；`must_change_password=true` 的用户只能访问登录/改密/me 接口。

## 架构关键点（易踩坑）

- **运行时以 catalog.db 为准**：`employees/*.yaml` 只是种子源。`seeds.seed_if_empty()` **只在 employees 表为空时全量播种**；仅 connectors / subagents / assignments 有幂等 backfill。→ 已有库中新增员工/技能/工具**不会自动出现**，需在资源中心手动建或清库重播种。新增员工 = yaml + `catalog/seeds.py` 的 `seeds` dict 注册 + 重启。
- **技能/SOP 不进 system_prompt**：SKILL.md/SOP 全文播种进 Store（`/skills/`、`/sops/` 命名空间），模型运行时 `read_file` 查阅。编辑 SKILL.md/SOP 只调 `runtime.sync_skills_to_store()` 刷新 Store，**不重编译 agent**。同理 `kb_search` 是运行时动态查库的闭包工具，知识库增删改也不重编译。
- **工具注册**：新工具在 `app/tools/` 定义后用 `@tool` 装饰，登记进 `compiler.ALL_LOCAL_TOOLS`。注意 `start_refund`（工厂，需运行时注入 checkpointer）与 `kb_search`（闭包）**不在该表**；`GLOBAL_TOOL_NAMES` 无条件给所有员工注入 `get_current_time`。给已有员工配新工具要在资源中心选中，种子只作用于新库。
- **MCP 连接器**：`${PYTHON_BIN}` 会被替换为本项目解释器（Python 型 stdio）；其他 command 原样透传（npx 型，如 newsnow 用 `cwd:/tmp` + `DOTENV_CONFIG_QUIET=true` 防 dotenv banner 污染协议通道）。连接器变更后新增需登记 `CONNECTOR_SEEDS`/`CONNECTOR_ASSIGN`，旧库靠 `backfill_connectors()` 幂等补缺。**`MCP_DISABLED=1` 可跳过 MCP 初始化**，MCP 故障不应拖垮服务启动。
- **backend 差异**：`local_shell` 后端的员工（xiaoshu、xiaoxiao、biz-analyzer）拿到原生 `execute`/`read_file`/`ls`/`write_file`；`run_python` 工作目录 = `workspace/data/`（按用户隔离）。
- **审批双路径**：轻量审批（create_ticket）走外层 agent 的 `interrupt_on` 拦截；退款审批（refund StateGraph）走**内层图** `interrupt()`，thread 名 `refund:{order_id}:{hash}`，decision 端点先 `resume_refund()` 恢复内层再 `Command(resume=...)` 恢复外层。
- **6 个 SQLite 库**（`data/db/` 或 `$APP_DATA_DIR`）：catalog / conversations / demo(checkpointer) / store(记忆) / traces / approvals。路径统一在 `app/paths.py`。

## 目录边界

- `backend/app/main.py` 网关（SSE 流/鉴权/静态挂载/生命周期）；`routes/` 拆分为 auth、conversations、admin、user、public、im；`catalog/` 拆为 db、employees、resources、seeds、users。
- `backend/app/streaming.py`：SSE 流式主逻辑（`recover_conversations` 启动恢复上限 `CONV_RECOVER_LIMIT=2000`）。
- `frontend/src/api.js` 自动注入 Bearer token 并 401 跳登录；`src/views/` 各页面顶部有中文文件说明。
- 详细文档见 `CLAUDE.md`（部分内容已过期：deepagents 实为 0.7.5、catalog 已是包而非单文件、含 approvals.db 与 IM 频道）。
