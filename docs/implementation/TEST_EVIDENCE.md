# 测试证据

## 0.21.2 · P0-SEC-01

日期：2026-10-08（Asia/Shanghai）
分支：`codex/v0.21.2-p0-sec-01`
基线：`abd8ed09dc744809d5478fa80f0fc60897740f55`

| 命令 | 结果 | 说明 |
|---|---|---|
| `PYTHONPATH=backend uv run python -m pytest -o addopts='' tests/test_automation_execution_routes.py tests/test_automations.py -q` | PASS：30 passed | Webhook HMAC、密钥脱敏、旧开发兼容、幂等、管理权限与人工重跑。 |
| `PYTHONPATH=backend uv run python -m pytest -o addopts='' tests/ -q` | PASS：565 passed、40 skipped（17.54s） | 仓库全量后端套件；测试夹具使用临时 SQLite。40 项按测试自身环境条件跳过，本轮未连接运行中的集成服务。 |
| `npm run build`（`frontend/`） | PASS | Vite 生产构建成功；输出包含既有的大 chunk 提示。 |
| `git diff --check` | PASS | 无空白错误。 |

未运行 PostgreSQL 集成、真实外部 Webhook、浏览器端到端或生产迁移测试；没有配置生产数据库或外部凭据用于本轮验证。

## 0.21.3 · P0-SEC-02

日期：2026-10-08（Asia/Shanghai）
分支：`codex/v0.21.3-p0-sec-02`（基于尚未合并的 PR #72）
基线：`f7bbbb76fdf409b98fefea10ef353c453d364e52`

| 命令 | 结果 | 说明 |
|---|---|---|
| `PYTHONPATH=backend uv run python -m pytest -o addopts='' tests/test_approvals.py tests/test_automation_identity.py tests/test_automation_execution_routes.py tests/test_automations.py -q` | PASS：41 passed | 同租户/有效运行身份、员工分配、停用后拒绝、管理员权限收敛、记录租户隔离、Webhook v2 跨租户签名、审批决策人及旧表迁移。 |
| `PYTHONPATH=backend uv run python -m pytest -o addopts='' tests/ -q` | PASS：573 passed、40 skipped（15.40s） | 仓库全量后端套件；测试夹具使用临时 SQLite。40 项因测试自身环境条件跳过。 |
| `npm run build`（`frontend/`） | PASS | Vite 生产构建通过；有既有的大 chunk 提示。 |
| `git diff --check` | PASS | 无空白错误。 |

未运行 PostgreSQL 集成、真实外部 Webhook、浏览器端到端或生产迁移演练。当前 CI 没有独立 PostgreSQL job。

## 0.21.4 · P0-ENV-01

日期：2026-10-08（Asia/Shanghai）
分支：`codex/v0.21.4-p0-env-01`（基于尚未合并的 PR #73；PR #73 依赖 #72）
基线：PR #73 head `a4cb31a`（启动时工作树干净）

| 命令 | 结果 | 说明 |
|---|---|---|
| `PYTHONPATH=backend uv run python -m pytest -o addopts='' tests/test_startup_preflight.py tests/test_demo_isolation.py tests/test_automations.py tests/test_automation_execution_routes.py tests/test_automation_identity.py -q` | PASS：60 passed | production fail-closed、开发脱敏警告、dotenv 先于模块路径解析、启动顺序、目录权限、Webhook UTF-8 字节长度、演示资产报告和非破坏性。 |
| `PYTHONPATH=backend uv run python -m pytest -o addopts='' tests/ -q` | PASS：592 passed、40 skipped（15.76s） | 全量后端；测试夹具使用临时 SQLite。 |
| `npm run build`（`frontend/`） | PASS | Vite 生产构建通过；存在既有大 chunk 警告。 |
| `git diff --check` | PASS | 无空白错误。 |

未运行 PostgreSQL 启动/迁移/恢复演练：本机 Docker daemon 不可用，且未找到 `initdb`、`pg_ctl`、`psql`。未连接现有数据库或生产数据。

## 0.21.5 · P0-TEST-01

日期：2026-10-08（Asia/Shanghai）
分支：`codex/v0.21.5-p0-test-01`（基于尚未合并的 PR #74；PR #74 → #73 → #72）
基线：PR #74 head `6818e1c`（工作树干净）

| 命令 | 结果 | 说明 |
|---|---|---|
| `PYTHONPATH=backend .venv/bin/python -m pytest -o addopts='' tests/ -m 'not pg_integration and not requires_live_server and not e2e and not requires_external_services' -q` | PASS：608 passed、1 skipped、42 deselected（18.62s） | SQLite 临时库；依赖 8787、Playwright 或外部服务的用例不混入常规结果；包含 P0-SEC-01/02 回归。 |
| `PYTHONPATH=backend .venv/bin/python -m pytest -o addopts='' tests/test_pg_test_database_safety.py tests/test_golden_eval_fixture.py tests/test_automation_execution_routes.py tests/test_automation_identity.py -q` | PASS：31 passed | PG 目标护栏、黄金 JSONL 读取契约、HMAC/幂等和自动化身份回归。 |
| `npm run build`（`frontend/`） | PASS | Vite 生产构建通过；有既有的大 chunk 警告。 |
| CI workflow YAML 解析 / `git diff --check` | PASS | 三个 job：`backend-test`、`postgres-integration`、`frontend-build`。 |

未在本机运行 PostgreSQL 集成测试：Docker daemon 不可用，且没有本机 PG 服务。没有访问或修改现有/生产数据库；真实 PG 结果待 PR CI 的一次性 PostgreSQL 16 service。黄金评测 loader 已有结构与授权引用校验，但仓库没有业务 owner 提供的标准答案，因此没有业务正确率结论。
