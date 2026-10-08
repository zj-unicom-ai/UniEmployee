# 实施状态

## 基线

- 任务书基线：`main` / `v0.21.1` / `abd8ed09dc744809d5478fa80f0fc60897740f55`（2026-10-02）
- 任务书基线后的执行起点：PR #72 分支提交 `f7bbbb76fdf409b98fefea10ef353c453d364e52`（尚未合并）
- 本轮分支：`codex/v0.21.3-p0-sec-02`（依赖 PR #72）
- 本轮版本：`0.21.3`
- 前置 P0-SEC-01 提交：`5931f5919b49798e7bdaefa570e18b76c3062643`
- 前置 Pull Request：[#72](https://github.com/zj-unicom-ai/UniEmployee/pull/72)
- 本轮 P0-SEC-02 实现提交：`87d19e9fe4aa836e2048cb24fa4be6e2a60e7071`
- 本轮 Pull Request：[#73](https://github.com/zj-unicom-ai/UniEmployee/pull/73)（栈式依赖 PR #72）
- 初始工作树干净；未连接生产数据库、CRM 或 RAGFlow。

## 任务状态

| 任务 | 状态 | 证据 / 缺口 |
|---|---|---|
| P0-SEC-01 Webhook 认证与密钥回显 | `verified-by-test` | 生产采用 HMAC-SHA256 v2；签名覆盖租户、方法、路径、时间戳、幂等键和请求体摘要；检查过期、篡改、跨租户复用、旧 body-secret、弱密钥、无密钥及重复请求；管理 API 不回传密钥。测试见 `TEST_EVIDENCE.md`。 |
| P0-SEC-02 自动任务身份与租户边界 | `verified-in-source` | 创建/启用校验有效用户、同租户和员工分配；执行前重查用户状态/租户/分配，传递服务端授权上下文并将 admin 权限收敛为 user；任务和执行记录按租户隔离，并保留 created_by / trigger_actor / run_as_principal；审批记录留存 decided_by。相关回归已通过，但项目无租户生命周期表，故“租户停用后拒绝运行”仍未实现，不能宣称完成 SaaS 租户治理。测试见 `TEST_EVIDENCE.md`。 |
| P0-ENV-01 生产启动预检 | `verified-in-source` | `demo_isolation.py` 已覆盖部分演示数据和连接器；一般安全配置预检尚缺，且现有演示隔离检查发生在部分初始化/播种之后。 |
| P0-TEST-01 PostgreSQL 集成 CI | `verified-in-source` | 当前 CI 有 SQLite 后端测试和前端构建；没有独立 PostgreSQL 集成 job。 |
| P0-BIZ-01 小网只读故障影响闭环 | `requires-business-acceptance` | 可先用合成数据验证技术链路；真实数据授权、黄金用例和业务 owner 签收仍待提供。 |
| P1-TASK / SOP / RUN / TOOL / RT / REL | `proposed` | 保留为后续独立任务；先确认业务试点和各自依赖，不在本轮扩建。 |

## 本轮实现

- 生产 Webhook 要求至少 32 字节任务密钥和 HMAC 签名；无签名/过期签名以认证失败拒绝。
- HMAC v2 使用 `v2\nMETHOD\nPATH\nTENANT_ID\nTIMESTAMP\nIDEMPOTENCY_KEY\nSHA256(BODY)` 规范串。相比任务书建议的 `timestamp + "." + body`，额外绑定租户、方法、路径与幂等键，避免跨租户复用、换幂等键重放或跨事件复用；修改原始请求体也会使签名失效。
- `Idempotency-Key` 保持数据库唯一约束去重；相同签名请求返回已存在的执行记录，不会再次启动 Agent。
- 仅开发环境保留旧 body `secret` 兼容；开发环境无密钥演示任务也保留，并写不含密钥的警告日志。
- 管理 API 仅返回 `has_secret`；前端编辑时不回填密钥，留空保留旧值，填写新值用于轮换。
- 自动化记录保存 `tenant_id`；管理 CRUD 与执行记录查询使用租户过滤，历史表启动时幂等补列。后台每次执行重查 `run_as` 用户、租户与员工分配；Agent 收到服务端 `auth_context`，权限固定收敛到普通用户集合。
- 执行记录区分 `created_by`、`trigger_actor` 和 `run_as_principal`；审批决策人记录在审批记录 `decided_by` 字段。Cron / Webhook / 手动执行采用不同触发主体标记。
- Webhook HMAC v2 加入任务租户 ID，避免同一 secret 在多个租户配置时产生跨租户触发。

## 剩余风险与迁移边界

- 自动化密钥仍按既有方式保存在数据库字段中；本轮未实现静态加密。数据库和备份访问控制仍是密钥保护边界，后续需单独设计密钥轮换与加密迁移。
- 生产旧集成必须迁移到 HMAC；生产不会接受请求体 `secret`。启用任务的现有密钥若少于 32 字节会被拒绝，需在部署前轮换。
- 0.21.3 将生产 HMAC 从 v1 升级为 v2；v2 调用方签名必须加入任务 `tenant_id`。无法解析为有效用户的旧 `run_as`、已撤销员工分配或租户不匹配会失败关闭，需管理员部署后核对任务。
- 当前只有单企业租户标识，没有租户生命周期数据模型；无法检查“租户被停用”，跨租户 SaaS 治理仍是未完成项。
- 同一 `event_key` 有多个监听任务时，每项任务各自验签；同密钥任务会一起触发，不同密钥只触发签名匹配的任务。
- 本轮测试使用测试夹具强制 SQLite；没有执行 PostgreSQL 集成、真实 Webhook 调用或生产数据迁移演练。
