# 配置参考：环境变量全量说明

UniEmployee 通过环境变量配置，应用启动时由 `backend/app/main.py` 加载项目根目录的 `.env`（`dotenv` 不会覆盖已存在的系统环境变量，容器部署时可直接注入）。

> 提示：`.env.example` 是最小可用模板；本文是全量参考。代码中读取位置的快捷检索方式：`grep -rn 'environ.get(' backend/app`。

## 模型

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `MODEL_NAME` | ✅ | — | 员工默认模型，格式为 `init_chat_model` 可识别的 `provider:model`，如 `openai:deepseek-chat`。员工 yaml 里的 `${MODEL_NAME}` 占位符在播种/编译时替换为该值；对话页可临时切换其他已登记模型 |
| `OPENAI_BASE_URL` | ✅* | — | OpenAI 兼容协议端点。DeepSeek 官方为 `https://api.deepseek.com`；任何兼容端点（vLLM / Xinference / One-API 等）均可，用于私有化部署 |
| `OPENAI_API_KEY` | ✅* | — | 对应端点的 API Key |

\* 走 OpenAI 兼容协议的模型时必填。接 Anthropic / Google 等原生 provider 时改用它们自己的凭据环境变量（`ANTHROPIC_API_KEY` / `GOOGLE_API_KEY`）。

## 安全与认证

| 变量 | 默认 | 说明 |
|---|---|---|
| `JWT_SECRET` | — | JWT 签名密钥，**必须**改为随机长字符串（≥32 字节，`openssl rand -hex 32`）。更换后所有已签发 token 立即失效 |
| `JWT_EXPIRE_HOURS` | `24` | token 有效期（小时） |
| `ADMIN_USER` | `admin` | 初始管理员用户名（仅空库首次启动创建，之后绝不重置已有账号） |
| `ADMIN_PASS` | `admin123` | 初始管理员密码；保持默认值时首登强制改密（`must_change_password`） |

## 数据库

| 变量 | 默认 | 说明 |
|---|---|---|
| `DB_BACKEND` | `postgres` | `postgres` / `sqlite`。**sqlite 仅测试夹具使用**（conftest 强制 sqlite 临时库），部署一律 postgres |
| `POSTGRES_HOST` | `127.0.0.1` | PG 实例地址 |
| `POSTGRES_PORT` | `5432` | PG 端口 |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | `uniemployee` / — | 连接凭据 |
| `POSTGRES_DB_PREFIX` | 空 | 库名前缀，多套环境共用一个 PG 实例时区分（如 `dev_`） |
| `APP_DATA_DIR` | `<项目根>/data/db` | 数据目录根。DB_BACKEND=sqlite 时 7 个 `.db` 文件放这里；postgres 模式下仍影响日志等本地产物路径。容器部署挂载卷时改为容器内路径 |

PostgreSQL 模式下应用会自动创建/迁移 7 个业务库：`catalog`（员工/技能/工具/连接器目录）、`conversations`（会话/产物文件/频道/自动化任务）、`checkpoints`（LangGraph 检查点）、`store`（长期记忆与技能规程）、`traces`（运行链路）、`approvals`（审批单）、`ontology`（业务本体）。

## 员工运行时

| 变量 | 默认 | 说明 |
|---|---|---|
| `MCP_DISABLED` | 空 | 置 `1` 跳过全部 MCP 连接器初始化（连接器故障不应拖垮服务启动时的保险开关） |
| `BOCHA_API_KEY` | — | 博查联网搜索 API Key，`bocha_search` 工具依赖；缺失时该工具返回错误提示 |
| `MARKET_INTEL_PUBLISH_WEBHOOK` | — | 市场简报发布外推地址：`publish_briefing` 经人工批准后，会把 `{title, summary, content_html, ...}` POST 到该 URL（如企业微信/钉钉群机器人） |
| `RUN_PYTHON_MAX_CODE_LEN` | `20000` | `run_python` 工具单次提交代码长度上限（字符） |
| `RUN_PYTHON_MAX_OUTPUT_LEN` | `6000` | `run_python` 输出截断上限（字符） |
| `ANALYST_QUERY_TIMEOUT_SEC` | `30` | 数据分析员工单条 SQL 服务端超时（秒） |
| `ANALYST_QUERY_MAX_ROWS` | `1000` | 分析 SQL 返回行数硬上限 |
| `ANALYST_DB_KEY` | — | 分析工作台外部数据库的解密密钥（数据源凭据加密存储时使用） |

## 审批与会话

| 变量 | 默认 | 说明 |
|---|---|---|
| `APPROVAL_PENDING_LIMIT` | `100` | 单用户待审批单上限，超限拒绝新审批请求 |
| `APPROVAL_TTL_SECONDS` | `86400` | 审批单过期时间（秒），过期未处理的审批单作废 |
| `MAX_ATTACHMENT_SIZE` | `20971520`（20MB） | 会话附件上传大小上限（字节） |
| `CONV_RECOVER_LIMIT` | `2000` | 服务启动时会话恢复的最大并发恢复量 |

## 自动化任务

| 变量 | 默认 | 说明 |
|---|---|---|
| `AUTOMATIONS_DISABLED` | 空 | 置 `1` 跳过进程内调度器（cron 任务不再触发；事件入口仍可用）。调试或禁用定时能力时使用 |

## 沙箱（OpenSandbox，可选）

`backend=sandbox` 的员工（如 net-ops）的 `execute`/文件工具在沙箱容器内执行；`SANDBOX_ENABLED` 未置 `1` 时自动回退宿主机 `local_shell`。

| 变量 | 默认 | 说明 |
|---|---|---|
| `SANDBOX_ENABLED` | 空 | 置 `1` 启用沙箱（需先部署 OpenSandbox server） |
| `SANDBOX_DOMAIN` | `localhost:8090` | OpenSandbox server 地址（app 也跑容器时用 `opensandbox-server:8090`） |
| `SANDBOX_PROTOCOL` | `http` | server 协议 |
| `SANDBOX_API_KEY` | — | server 配置了 api_key 时填写（生产建议开启） |
| `SANDBOX_IMAGE` | `uniemployee/sandbox:py312-data` | 沙箱镜像，需预装 pandas/duckdb/matplotlib/openpyxl/python-docx |
| `SANDBOX_HOST_DATA` | — | **宿主机**上 `workspace/data` 的绝对路径（server 通过 docker.sock 按 subPath 挂载进沙箱 `/data`） |
| `SANDBOX_HOST_DATASETS` | — | 宿主机上 `workspace/datasets` 绝对路径（共享数据集，只读挂到 `/datasets`） |
| `SANDBOX_TTL_MINUTES` | `30` | 沙箱空闲回收时间（分钟） |
| `SANDBOX_CMD_TIMEOUT` | `1800` | 沙箱内单命令超时（秒） |
| `SANDBOX_CPU` / `SANDBOX_MEMORY` | `1` / `2Gi` | 单沙箱资源上限 |
| `SANDBOX_MAX_CONCURRENT` | `20` | 单进程并发沙箱数上限（按会话计，超限抛错） |

## 知识库（RAGFlow）

| 变量 | 默认 | 说明 |
|---|---|---|
| `RAGFLOW_BASE_URL` | `http://localhost` | RAGFlow 服务地址 |
| `RAGFLOW_API_KEY` | — | RAGFlow API Key（UI 的 API 页面创建） |
| `RAGFLOW_DATASET_IDS` | 空 | 逗号分隔的 dataset id 白名单；留空则检索该 key 可见的全部数据集 |

## 运维杂项

| 变量 | 默认 | 说明 |
|---|---|---|
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `LOG_FILE` | 空（仅控制台） | 日志同时写入的文件路径，容器部署配合卷挂载 |
| `APP_VERSION` | 取 `backend/app/main.py` 常量 | 覆盖 `/health` 与日志打印的版本号 |

## 相关文档

- [部署指南](./deployment.md)——裸机 / Docker Compose / 已有 PG 实例
- [新增数字员工指南](./add-employee.md)——员工 yaml 与种子注册
- 原理向解读见 [docs/articles](../articles/README.md)（编译机制 / HITL / Trace 系列）
