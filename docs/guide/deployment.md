# 部署指南

三种部署形态按需选择：**裸机开发**（最快跑通）、**Docker Compose 全栈**（推荐的生产形态）、**已有 PostgreSQL 实例接入**（公司共享库）。

## 形态一：裸机（开发/体验）

前置：Python 3.12+、Node.js 18+、Docker（起库用）。

```bash
# 1. 配置
cp .env.example .env        # 至少填 MODEL_NAME / OPENAI_BASE_URL / OPENAI_API_KEY / JWT_SECRET

# 2. 依赖
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock.txt

# 3. 起 PostgreSQL（首次启动自动建 7 个业务库，表结构由应用启动时自动创建）
docker compose up -d db

# 4. 启动服务（--reload 开发热加载；改后端代码会顺带清 agent 编译缓存）
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --port 8787 --reload

# 前端开发才需要（生产由 FastAPI 静态托管 frontend/dist）
cd frontend && npx vite
```

验证：浏览器开 `http://localhost:8787`，默认账号 `admin / admin123`（首登强制改密）；或 `curl http://localhost:8787/readyz` 应返回 `"status":"ok"` 与 7 个库的 ok 状态。

## 形态二：Docker Compose 全栈（推荐）

```bash
cp .env.example .env    # 填好密钥
docker compose up -d --build
curl http://localhost:8787/readyz
```

编排内容（`docker-compose.yml`）：

- `db`：PostgreSQL 16 + `scripts/init_postgres.sql` 自动建 7 个业务库，数据落在命名卷 `pgdata`；
- `uniemployee`：应用镜像（`backend/Dockerfile`，前后端一体），`.env` 经 `env_file` 注入密钥，挂载 `backend/skills`（技能目录热改）、`workspace`（产物文件）两个卷，healthcheck 走 `/readyz`；`/livez` 只表示进程存活，`/health` 保留为兼容旧监控的 200 状态结构。

生产化追加清单：

- [ ] 在 `.env` 设置 `APP_ENV=production`；使用独立的新库接入真实数据，旧演示库先核对并隔离 `seed` 来源实体和实验 CRM 指派，移出 `workspace` 中的已知模拟 CSV（程序不自动删除），逐项核对 RAGFlow 知识库来源
- [ ] `JWT_SECRET` 换随机长串；登录后立即改默认管理员密码（保持 `admin123` 时系统会强制首登改密）
- [ ] 前面加 HTTPS 反向代理（Nginx/Caddy），不要裸露 8787
- [ ] `LOG_FILE` 指到挂载卷，配日志轮转
- [ ] 配置每日备份（见下）
- [ ] 执行型员工在生产模式下必须启用 `SANDBOX_ENABLED=1` 并部署 OpenSandbox；给 server 配 `SANDBOX_API_KEY` 并去掉其 `OPENSANDBOX_INSECURE_SERVER`，实测容器挂载和密钥隔离
- [ ] 用到 Playwright 连接器时确认镜像内已 `npx playwright install --with-deps chromium`

## 形态三：已有 PostgreSQL 实例

```bash
# 幂等建库（已存在则跳过），连接参数优先级：命令行 > .env > 默认值
./scripts/init_postgres.sh --host 10.0.0.5 --port 5432 --user me --password xx
# 或指定已有容器名：
./scripts/init_postgres.sh --docker my-pg-container
```

多套环境共用一个实例时，在 `.env` 设 `POSTGRES_DB_PREFIX=dev_` 区分库名。应用启动时自动建表/迁移，无需手工执行 SQL。

## 生产 Webhook 认证

生产模式下，启用的事件自动化必须设置至少 32 字节的任务密钥。管理 API 只返回 `has_secret`，不会回显密钥；编辑时留空表示保留原密钥，填写新值会轮换密钥。部署前请在管理页更新旧任务密钥，并让调用方改用 HMAC 请求；生产环境不接受旧版请求体 `secret`。

签名为 HMAC-SHA256 十六进制小写值。0.21.3 起使用 v2：签名消息由以下字段按换行符连接后 UTF-8 编码：`v2`、大写 HTTP 方法、请求路径、任务租户 ID、Unix 秒级时间戳、`Idempotency-Key`、原始请求体的 SHA-256 十六进制摘要。签名绑定租户，避免同事件标识或误复用密钥导致跨租户触发。时间戳默认允许前后偏差 300 秒，可用 `AUTOMATION_WEBHOOK_TOLERANCE_SECONDS` 调整（1–3600 秒）。0.21.3 生产环境拒绝旧版 v1 签名；升级时需同步更新调用方签名算法。

```python
import hashlib
import hmac
import time
import requests

secret = "替换为管理页中配置的至少 32 字节密钥"
tenant_id = "default"  # 必须与任务运行身份所属租户一致
path = "/api/automations/events/order.refunded"
body = b'{"payload":{"order_id":"A-1001"}}'
timestamp = str(int(time.time()))
idempotency_key = "order-refunded-A-1001-v1"  # 网络重试沿用同一个值
body_digest = hashlib.sha256(body).hexdigest()
message = "\n".join(("v2", "POST", path, tenant_id, timestamp,
                      idempotency_key, body_digest)).encode("utf-8")
signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

response = requests.post(
    "https://example.com" + path,
    data=body,
    headers={
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency_key,
        "X-UniEmployee-Timestamp": timestamp,
        "X-UniEmployee-Signature": signature,
    },
    timeout=30,
)
response.raise_for_status()
```

迁移顺序：先为每个生产事件任务设置新密钥并安全交付给对应调用方，再切换调用方签名实现，最后将 `APP_ENV=production` 部署。不要把密钥放进事件 payload、命令行参数或日志。重复请求必须复用原幂等键；更换幂等键会被视为一次新触发。

## 自动化运行身份

自动化任务按其保存的“运行身份”执行。创建或启用任务时，该身份必须是当前租户的有效用户，并已获授权使用所选数字员工；每次 Cron、Webhook、手动运行前都会重新检查用户状态和员工分配。用户被禁用、员工分配被撤销或租户不匹配时，本次执行会失败关闭，不创建会话或调用 Agent。

Agent 收到的授权上下文来自服务端用户目录，不来自 webhook payload 或请求头。后台自动任务即使以管理员用户 ID 作为运行身份，也只按普通用户权限执行，不继承管理员的全局 `*` 权限。执行记录分别保存 `created_by`（配置创建者）、`trigger_actor`（触发来源/操作者）和 `run_as_principal`（实际运行主体）；审批决策人在审批记录的 `decided_by` 字段单独记录。

升级后请检查已有启用任务的运行身份。无法解析为有效用户的旧 `default`、已删除/停用用户或没有目标员工分配的身份不会自动改派，触发时会留下失败记录，需管理员在自动化页面修正。执行身份、租户与审计字段由应用启动时幂等迁移；当前项目只有单企业租户标识，没有租户生命周期管理，不能据此视为已支持 SaaS 多租户。

## 备份与恢复

```bash
./scripts/backup.sh                    # 备份到项目根/backups，默认保留 7 份
BACKUP_KEEP=30 ./scripts/backup.sh /data/backups   # 自定义目录与保留份数
PGBIN=/opt/homebrew/opt/postgresql@16/bin ./scripts/backup.sh   # 指定 pg_dump 位置
BACKUP_PG_CONTAINER=uniemployee-pg ./scripts/backup.sh  # 宿主机没有 pg_dump 时使用容器内工具
```

脚本对 7 个业务库逐个 `pg_dump -Fc`，并将 `workspace` 和 `manifest.txt` 一起打包成带时间戳的 tar.gz；连接参数默认从 `.env` 读取。数据库导出或文件归档失败都会返回非 0，且不生成正式归档。定时备份可用 crontab：`0 3 * * * /path/to/scripts/backup.sh`。在线备份清单标记为 `online_uncoordinated`：逐库导出和文件复制不是同一事务时间点。需要一致恢复点时，先暂停应用写入，再以 `BACKUP_QUIESCED=1` 执行备份；这个变量只记录操作状态，不会替你暂停写入。

恢复：停止应用写入，解包到空目录；确认 `manifest.txt` 的库前缀及一致性标记，先将 `pg/*.dump` 分别用 `pg_restore -U <user> -d <目标库> --clean` 恢复到对应业务库，再恢复 `workspace/`，最后重启应用并核对会话、Trace、上传文件和生成产物。不要在未确认目标库和文件路径前对现有环境执行覆盖恢复。

隔离演练：`PYTHONPATH=backend .venv/bin/python scripts/verify_backup_restore.py --pg-container <隔离PG容器> --pg-port <映射端口> --env-file <隔离凭据文件>`。脚本只创建临时前缀的 14 个库，验证 7 库及 workspace 的备份恢复，完成后删除这些临时库；不对现有业务库执行恢复。

## 升级

```bash
git pull
docker compose up -d --build      # 或裸机：重启 uvicorn
```

升级是安全的：启动时自动做表结构迁移、幂等补种缺失的员工/工具/任务模板（`backfill_*` 系列），不覆盖管理员在资源中心的改动。

## 排障速查

| 现象 | 检查 |
|---|---|
| `/readyz` 返回 503 或某库不是 ok | PG 连接参数/网络；容器网络内 `POSTGRES_HOST=db` 而非 localhost |
| 员工列表缺新员工 | 老库靠 backfill 补种，确认升级到了含该员工的版本并已重启 |
| 改了人设/工具没生效 | agent 编译缓存按"员工+用户+模型"缓存，**重启服务** |
| 技能规程改了没生效 | 正文改动会热同步；frontmatter `description` 改动需重启 |
| MCP 工具全部缺失 | 查是否设了 `MCP_DISABLED=1`；npx 型连接器看服务端日志的 stderr |
| 沙箱员工执行失败 | `SANDBOX_ENABLED=1`？server 可达？`SANDBOX_HOST_DATA/DATASETS` 是否为宿主机绝对路径且在 server 白名单内 |
| 联网搜索报错 | `BOCHA_API_KEY` 未配或欠费 |

## 相关文档

- [配置参考](./configuration.md)——全部环境变量逐项说明
- [README 常见问题](../../README.md#常见问题)
- [新增数字员工指南](./add-employee.md)
