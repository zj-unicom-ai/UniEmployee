#!/usr/bin/env bash
# UniEmployee PostgreSQL 建库脚本（幂等，可重复执行）
# ---------------------------------------------------------------
# 创建登录角色 + 7 个业务库（已存在则跳过）。
# 适用于：已有 PostgreSQL 实例（本地 docker 容器 / 公司共享实例均可）。
#
# 连接参数优先级：命令行参数 > .env（POSTGRES_*）> 默认值。
#
# 用法：
#   ./scripts/init_postgres.sh                     # 自动检测 uniemployee-pg 容器，否则用 psql
#   ./scripts/init_postgres.sh --docker mycontainer # 指定容器名
#   ./scripts/init_postgres.sh --host 10.0.0.5 --port 5432 --user me --password xx
#
# 之后在 .env 里设置 DB_BACKEND=postgres 并启动服务即可：
#   PYTHONPATH=backend .venv/bin/uvicorn app.main:app --port 8787
# 表结构由应用启动时自动创建，无需手工执行 DDL。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/.."

# ---- 默认值 / 读 .env ----
HOST="127.0.0.1" PORT="5432" USER="uniemployee" PASSWORD="" PREFIX=""
if [ -f "$PROJECT_DIR/.env" ]; then
  # grep 无匹配返回 1，在 set -e 下会中断脚本，加 || true 兜底
  _env() { grep -E "^$1=" "$PROJECT_DIR/.env" | tail -1 | cut -d= -f2- | tr -d ' \r' || true; }
  HOST="$(_env POSTGRES_HOST)"; HOST="${HOST:-127.0.0.1}"
  PORT="$(_env POSTGRES_PORT)"; PORT="${PORT:-5432}"
  USER="$(_env POSTGRES_USER)"; USER="${USER:-uniemployee}"
  PASSWORD="$(_env POSTGRES_PASSWORD)"
  PREFIX="$(_env POSTGRES_DB_PREFIX)"
fi

DOCKER_CONTAINER=""

while [ $# -gt 0 ]; do
  case "$1" in
    --docker)  DOCKER_CONTAINER="$2"; shift 2 ;;
    --host)    HOST="$2"; shift 2 ;;
    --port)    PORT="$2"; shift 2 ;;
    --user)    USER="$2"; shift 2 ;;
    --password) PASSWORD="$2"; shift 2 ;;
    --prefix)  PREFIX="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

# 自动检测本地容器（名字含 uniemployee-pg / postgres 均可）
if [ -z "$DOCKER_CONTAINER" ]; then
  if command -v docker >/dev/null 2>&1; then
    for c in $(docker ps --format '{{.Names}}' 2>/dev/null); do
      case "$c" in *uniemployee-pg*|*postgres*) DOCKER_CONTAINER="$c"; break ;; esac
    done
  fi
fi

# ---- 执行 SQL 的通道：docker exec 或本地 psql（额外参数原样透传给 psql） ----
run_psql() {
  if [ -n "$DOCKER_CONTAINER" ]; then
    docker exec -i "$DOCKER_CONTAINER" psql -U "$USER" -d postgres -v ON_ERROR_STOP=1 "$@"
  else
    if ! command -v psql >/dev/null 2>&1; then
      echo "[错误] 未找到 psql，且未检测到运行中的 PostgreSQL 容器。"
      echo "  方案 1：docker compose up -d db（项目自带，首次启动自动建库，无需本脚本）"
      echo "  方案 2：安装 psql 后重试，或用 --docker 指定容器名"
      exit 1
    fi
    PGPASSWORD="$PASSWORD" psql -h "$HOST" -p "$PORT" -U "$USER" -d postgres -v ON_ERROR_STOP=1 "$@"
  fi
}

if [ -n "$DOCKER_CONTAINER" ]; then
  echo "通过容器 $DOCKER_CONTAINER 执行"
else
  echo "通过 psql 连接 $HOST:$PORT（用户 $USER）执行"
fi

# ---- 建角色（幂等）+ 建库（幂等） ----
# 说明：连的是 postgres 管理库；若用无权建库的普通账号连接，会报错——
# 此时请让 DBA 建好角色与 7 个库的所有权。
if ! run_psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$USER'" | grep -q 1; then
  echo "创建角色 $USER"
  run_psql <<SQL
CREATE ROLE "$USER" LOGIN PASSWORD '$PASSWORD';
SQL
fi

echo "创建业务库（前缀: '${PREFIX:-无}'）"
for db in catalog conversations checkpoints store traces approvals ontology; do
  full="${PREFIX}${db}"
  if run_psql -tAc "SELECT 1 FROM pg_database WHERE datname='$full'" | grep -q 1; then
    echo "  库 $full 已存在，跳过"
  else
    run_psql -c "CREATE DATABASE \"$full\" OWNER \"$USER\""
    echo "  库 $full 已创建"
  fi
done

echo "完成。.env 设置 DB_BACKEND=postgres 后启动服务即可（表结构应用会自动建）。"
