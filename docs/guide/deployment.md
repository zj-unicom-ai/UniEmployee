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

验证：浏览器开 `http://localhost:8787`，默认账号 `admin / admin123`（首登强制改密）；或 `curl http://localhost:8787/health` 应返回 `"status":"ok"` 与 7 个库的 ok 状态。

## 形态二：Docker Compose 全栈（推荐）

```bash
cp .env.example .env    # 填好密钥
docker compose up -d --build
curl http://localhost:8787/health
```

编排内容（`docker-compose.yml`）：

- `db`：PostgreSQL 16 + `scripts/init_postgres.sql` 自动建 7 个业务库，数据落在命名卷 `pgdata`；
- `uniemployee`：应用镜像（`backend/Dockerfile`，前后端一体），`.env` 经 `env_file` 注入密钥，挂载 `backend/skills`（技能目录热改）、`workspace`（产物文件）两个卷，healthcheck 走 `/health`。

生产化追加清单：

- [ ] `JWT_SECRET` 换随机长串；登录后立即改默认管理员密码（保持 `admin123` 时系统会强制首登改密）
- [ ] 前面加 HTTPS 反向代理（Nginx/Caddy），不要裸露 8787
- [ ] `LOG_FILE` 指到挂载卷，配日志轮转
- [ ] 配置每日备份（见下）
- [ ] 启用沙箱时给 server 配 `SANDBOX_API_KEY` 并去掉其 `OPENSANDBOX_INSECURE_SERVER`
- [ ] 用到 Playwright 连接器时确认镜像内已 `npx playwright install --with-deps chromium`

## 形态三：已有 PostgreSQL 实例

```bash
# 幂等建库（已存在则跳过），连接参数优先级：命令行 > .env > 默认值
./scripts/init_postgres.sh --host 10.0.0.5 --port 5432 --user me --password xx
# 或指定已有容器名：
./scripts/init_postgres.sh --docker my-pg-container
```

多套环境共用一个实例时，在 `.env` 设 `POSTGRES_DB_PREFIX=dev_` 区分库名。应用启动时自动建表/迁移，无需手工执行 SQL。

## 备份与恢复

```bash
./scripts/backup.sh                    # 备份到项目根/backups，默认保留 7 份
BACKUP_KEEP=30 ./scripts/backup.sh /data/backups   # 自定义目录与保留份数
PGBIN=/opt/homebrew/opt/postgresql@16/bin ./scripts/backup.sh   # 指定 pg_dump 位置
```

脚本对 7 个业务库逐个 `pg_dump -Fc` 打包成带时间戳的 tar.gz，连接参数自动从 `.env` 读取。建议 crontab 每日一次：`0 3 * * * /path/to/scripts/backup.sh`。

恢复：解包后对每个库 `pg_restore -U <user> -d <库名> --clean <dump文件>`，再重启应用。

## 升级

```bash
git pull
docker compose up -d --build      # 或裸机：重启 uvicorn
```

升级是安全的：启动时自动做表结构迁移、幂等补种缺失的员工/工具/任务模板（`backfill_*` 系列），不覆盖管理员在资源中心的改动。

## 排障速查

| 现象 | 检查 |
|---|---|
| `/health` 某库不是 ok | PG 连接参数/网络；容器网络内 `POSTGRES_HOST=db` 而非 localhost |
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
