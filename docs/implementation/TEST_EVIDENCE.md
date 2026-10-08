# 测试证据

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
