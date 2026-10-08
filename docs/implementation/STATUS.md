# 实施状态

## 基线

- 任务书基线：`main` / `v0.21.1` / `abd8ed09dc744809d5478fa80f0fc60897740f55`（2026-10-02）
- 任务书基线后的执行起点：PR #72 分支提交 `f7bbbb76fdf409b98fefea10ef353c453d364e52`（尚未合并）
- 本轮分支：`codex/v0.21.5-p0-test-01`（依赖 PR #74；PR #74 → #73 → #72）
- 本轮版本：`0.21.5`
- 前置 P0-SEC-01 提交：`5931f5919b49798e7bdaefa570e18b76c3062643`
- 前置 Pull Request：[#72](https://github.com/zj-unicom-ai/UniEmployee/pull/72)
- 前置 P0-SEC-02 实现提交：`87d19e9fe4aa836e2048cb24fa4be6e2a60e7071`
- 前置 Pull Request：[#73](https://github.com/zj-unicom-ai/UniEmployee/pull/73)（栈式依赖 PR #72）
- 本轮 P0-ENV-01 实现提交：`98b6f798972a773ca7be3da3043e0bc01fad074f`
- 本轮 Pull Request：[#74](https://github.com/zj-unicom-ai/UniEmployee/pull/74)（栈式依赖 PR #73 → #72）
- 本轮 P0-TEST-01 实现提交：`337d9f2ab65e55deb09c2e5da0c53a415542a62d`
- 本轮 P0-TEST-01 Pull Request：待推送后创建（基于 PR #74）
- 初始工作树干净；未连接生产数据库、CRM 或 RAGFlow。

## 任务状态

| 任务 | 状态 | 证据 / 缺口 |
|---|---|---|
| P0-SEC-01 Webhook 认证与密钥回显 | `verified-by-test` | 生产采用 HMAC-SHA256 v2；签名覆盖租户、方法、路径、时间戳、幂等键和请求体摘要；检查过期、篡改、跨租户复用、旧 body-secret、弱密钥、无密钥及重复请求；管理 API 不回传密钥。测试见 `TEST_EVIDENCE.md`。 |
| P0-SEC-02 自动任务身份与租户边界 | `verified-in-source` | 创建/启用校验有效用户、同租户和员工分配；执行前重查用户状态/租户/分配，传递服务端授权上下文并将 admin 权限收敛为 user；任务和执行记录按租户隔离，并保留 created_by / trigger_actor / run_as_principal；审批记录留存 decided_by。相关回归已通过，但项目无租户生命周期表，故“租户停用后拒绝运行”仍未实现，不能宣称完成 SaaS 租户治理。测试见 `TEST_EVIDENCE.md`。 |
| P0-ENV-01 生产启动预检 | `verified-in-source` | 生产环境配置门禁在数据库初始化前运行；旧库 CRM 指派、本体 seed、workspace 模拟 CSV 在数据播种/资源回填前汇总并 fail closed，不删除/迁移数据；enabled Webhook 弱密钥被拒绝。RAGFlow 来源、外部 HTTPS、OIDC 本地登录策略、备份和恢复需人工确认。尚未完成隔离 PostgreSQL 启动/迁移/恢复演练。 |
| P0-TEST-01 PostgreSQL 集成 CI | `verified-in-source` | CI 增加 SQLite、PostgreSQL 16、前端三个独立 job；PG 测试在本机未执行，待 PR 的隔离服务结果确认。真实业务黄金答案未提供，因此只建读取契约、不报告答案正确率。 |
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

## P0-ENV-01 实现

- 项目 `.env` 在计算 `DATA_DIR`、导入 `auth.SECRET` 等模块级配置前加载；FastAPI lifespan 起始即执行生产预检，失败时不进入 catalog/ontology 初始化、播种或资源回填。
- 生产要求强/非占位 JWT、PostgreSQL 非默认密码、Secure Cookie、已启用且有 API key 的 OpenSandbox、显式 RAGFlow 数据集 allowlist；配置了部分 OIDC 时拒绝启动。
- 检查 workspace 与可选 `LOG_FILE` 的可写位置；启用的事件自动化必须有至少 32 字节 Webhook 密钥。
- 已知演示 CRM 连接器、本体 seed 数据和递归 workspace 模拟 CSV 汇总为报告；发现时拒绝启动，不执行数据删除/移动/迁移。已配置的 RAGFlow 数据集来源留给人工核验；HTTPS 反向代理、未启用 OIDC 的本地登录策略、备份/恢复计划由日志提示人工确认。
- 定向回归 60 passed；后端全量 592 passed / 40 skipped；前端 build 通过。测试在 SQLite 临时库上验证启动顺序与拒绝行为；隔离 PostgreSQL migration/restore 演练仍待执行。

## P0-TEST-01 实现

- CI 现在分别报告 SQLite 单测/进程内服务测试、PostgreSQL 16 集成测试和前端构建。PG job 只建 `codex_test_` 前缀数据库；测试入口要求显式 opt-in，并校验 PG 后端、本机/CI 服务地址、5432 端口及连接凭据，且只允许收集 `tests/pg_integration/`。
- 测试分类：8 个依赖本机 8787 的文件标记 `requires_live_server`；其中 4 个还标记 `e2e`（Playwright）；Bocha 搜索标记 `requires_external_services`。常规 CI 明确排除三类以及 PG 标记。
- PG 集成用例涵盖自动化旧表迁移、事务回滚、并发唯一键幂等、租户查询隔离、真实 HMAC Webhook 重放和 LangGraph Checkpoint/Store 存取，不调用真实 LLM。
- `golden_eval_cases` fixture 可读取 owner 授权的 JSONL，校验稳定 ID、预期事实、来源约束和授权引用。仓库未添加虚构黄金样例；无业务 owner 提供标准答案时不运行答案正确率验收。
- 首轮 PG 集成是否通过以 PR CI 结果为准；该 job 不替代生产数据库迁移、备份或恢复演练。

## 剩余风险与迁移边界

- 自动化密钥仍按既有方式保存在数据库字段中；本轮未实现静态加密。数据库和备份访问控制仍是密钥保护边界，后续需单独设计密钥轮换与加密迁移。
- 生产旧集成必须迁移到 HMAC；生产不会接受请求体 `secret`。启用任务的现有密钥若少于 32 字节会被拒绝，需在部署前轮换。
- 0.21.3 将生产 HMAC 从 v1 升级为 v2；v2 调用方签名必须加入任务 `tenant_id`。无法解析为有效用户的旧 `run_as`、已撤销员工分配或租户不匹配会失败关闭，需管理员部署后核对任务。
- 0.21.4 生产启动默认 fail closed：必须配置 `DB_BACKEND=postgres`、强 JWT、非默认 PG 密码、安全 cookie 与认证沙箱；RAGFlow key 必须配 dataset allowlist，启用中的事件任务必须有强 webhook secret。
- 当前只有单企业租户标识，没有租户生命周期数据模型；无法检查“租户被停用”，跨租户 SaaS 治理仍是未完成项。
- 同一 `event_key` 有多个监听任务时，每项任务各自验签；同密钥任务会一起触发，不同密钥只触发签名匹配的任务。
- 本轮测试使用测试夹具强制 SQLite；没有执行 PostgreSQL 集成、真实 Webhook 调用或生产数据迁移演练。
