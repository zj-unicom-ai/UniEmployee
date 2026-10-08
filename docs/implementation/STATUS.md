# 实施状态

## 基线

- 任务书基线：`main` / `v0.21.1` / `abd8ed09dc744809d5478fa80f0fc60897740f55`（2026-10-02）
- 本轮分支：`codex/v0.21.2-p0-sec-01`
- 本轮版本：`0.21.2`
- 初始工作树干净；未连接生产数据库、CRM 或 RAGFlow。

## 任务状态

| 任务 | 状态 | 证据 / 缺口 |
|---|---|---|
| P0-SEC-01 Webhook 认证与密钥回显 | `verified-by-test` | 生产采用 HMAC-SHA256；签名覆盖方法、路径、时间戳、幂等键和请求体摘要；检查过期、篡改、旧 body-secret、弱密钥、无密钥及重复请求；管理 API 不回传密钥。测试见 `TEST_EVIDENCE.md`。 |
| P0-SEC-02 自动任务身份与租户边界 | `verified-in-source` | 已确认自动化通过 `run_as` 启动 `_stream_run` 时未传完整 `tenant_id` / `auth_context`；会话默认租户，员工分配缺失时运行时会回退模板。尚未实施。 |
| P0-ENV-01 生产启动预检 | `verified-in-source` | `demo_isolation.py` 已覆盖部分演示数据和连接器；一般安全配置预检尚缺，且现有演示隔离检查发生在部分初始化/播种之后。 |
| P0-TEST-01 PostgreSQL 集成 CI | `verified-in-source` | 当前 CI 有 SQLite 后端测试和前端构建；没有独立 PostgreSQL 集成 job。 |
| P0-BIZ-01 小网只读故障影响闭环 | `requires-business-acceptance` | 可先用合成数据验证技术链路；真实数据授权、黄金用例和业务 owner 签收仍待提供。 |
| P1-TASK / SOP / RUN / TOOL / RT / REL | `proposed` | 保留为后续独立任务；先确认业务试点和各自依赖，不在本轮扩建。 |

## 本轮实现

- 生产 Webhook 要求至少 32 字节任务密钥和 HMAC 签名；无签名/过期签名以认证失败拒绝。
- HMAC 使用 `v1\nMETHOD\nPATH\nTIMESTAMP\nIDEMPOTENCY_KEY\nSHA256(BODY)` 规范串。相比任务书建议的 `timestamp + "." + body`，额外绑定方法、路径与幂等键，避免合法签名被换幂等键重放或跨事件复用；修改原始请求体也会使签名失效。
- `Idempotency-Key` 保持数据库唯一约束去重；相同签名请求返回已存在的执行记录，不会再次启动 Agent。
- 仅开发环境保留旧 body `secret` 兼容；开发环境无密钥演示任务也保留，并写不含密钥的警告日志。
- 管理 API 仅返回 `has_secret`；前端编辑时不回填密钥，留空保留旧值，填写新值用于轮换。

## 剩余风险与迁移边界

- 自动化密钥仍按既有方式保存在数据库字段中；本轮未实现静态加密。数据库和备份访问控制仍是密钥保护边界，后续需单独设计密钥轮换与加密迁移。
- 生产旧集成必须迁移到 HMAC；生产不会接受请求体 `secret`。启用任务的现有密钥若少于 32 字节会被拒绝，需在部署前轮换。
- 同一 `event_key` 有多个监听任务时，每项任务各自验签；同密钥任务会一起触发，不同密钥只触发签名匹配的任务。
- 本轮测试使用测试夹具强制 SQLite；没有执行 PostgreSQL 集成、真实 Webhook 调用或生产数据迁移演练。
