#!/usr/bin/env bash
# UniEmployee 备份：7 个 PostgreSQL 业务库 + workspace 文件。
# 用法：./scripts/backup.sh [备份目录]
# 连接参数默认从项目 .env 读取；BACKUP_ENV_FILE 可指定另一套环境。
# 宿主机 pg_dump 不可用时，设置 BACKUP_PG_CONTAINER 使用 Docker 容器内 pg_dump。
set -euo pipefail
umask 077

BACKUP_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_PROJECT_DIR="$BACKUP_SCRIPT_DIR/.."
BACKUP_OUTPUT_DIR="${1:-$BACKUP_PROJECT_DIR/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"
BACKUP_ENV_FILE="${BACKUP_ENV_FILE:-$BACKUP_PROJECT_DIR/.env}"
BACKUP_WORKSPACE_DIR="${BACKUP_WORKSPACE_DIR:-$BACKUP_PROJECT_DIR/workspace}"
BACKUP_PG_CONTAINER="${BACKUP_PG_CONTAINER:-}"
BACKUP_TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP_DBS=(catalog conversations checkpoints store traces approvals ontology)

read_env() {
  local key="$1"
  if [ -f "$BACKUP_ENV_FILE" ]; then
    grep -E "^${key}=" "$BACKUP_ENV_FILE" | tail -1 | cut -d= -f2- | tr -d '\r' || true
  fi
}

BACKUP_PG_HOST="${BACKUP_PG_HOST:-$(read_env POSTGRES_HOST)}"
BACKUP_PG_PORT="${BACKUP_PG_PORT:-$(read_env POSTGRES_PORT)}"
BACKUP_PG_USER="${BACKUP_PG_USER:-$(read_env POSTGRES_USER)}"
BACKUP_PG_PASSWORD="${BACKUP_PG_PASSWORD:-$(read_env POSTGRES_PASSWORD)}"
BACKUP_DB_PREFIX="${BACKUP_DB_PREFIX:-$(read_env POSTGRES_DB_PREFIX)}"
BACKUP_PG_HOST="${BACKUP_PG_HOST:-127.0.0.1}"
BACKUP_PG_PORT="${BACKUP_PG_PORT:-5432}"
BACKUP_PG_USER="${BACKUP_PG_USER:-uniemployee}"

if ! [[ "$BACKUP_KEEP" =~ ^[0-9]+$ ]]; then
  echo "BACKUP_KEEP 必须是非负整数" >&2
  exit 1
fi
if [ ! -d "$BACKUP_WORKSPACE_DIR" ]; then
  echo "workspace 目录不存在：$BACKUP_WORKSPACE_DIR" >&2
  exit 1
fi
BACKUP_WORKSPACE_DIR="$(cd "$BACKUP_WORKSPACE_DIR" && pwd -P)"
if [ "$(basename "$BACKUP_WORKSPACE_DIR")" != "workspace" ]; then
  echo "BACKUP_WORKSPACE_DIR 必须指向名为 workspace 的目录" >&2
  exit 1
fi
mkdir -p "$BACKUP_OUTPUT_DIR"
BACKUP_OUTPUT_DIR="$(cd "$BACKUP_OUTPUT_DIR" && pwd -P)"
case "$BACKUP_OUTPUT_DIR/" in
  "$BACKUP_WORKSPACE_DIR/"*)
    echo "备份目录不能位于 workspace 内，避免归档包含自身" >&2
    exit 1
    ;;
esac

if [ -n "$BACKUP_PG_CONTAINER" ]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "BACKUP_PG_CONTAINER 已设置，但找不到 docker" >&2
    exit 1
  fi
else
  BACKUP_PGDUMP="${PGBIN:+$PGBIN/}pg_dump"
  if ! command -v "$BACKUP_PGDUMP" >/dev/null 2>&1; then
    echo "找不到 pg_dump；可设置 PGBIN 或 BACKUP_PG_CONTAINER" >&2
    exit 1
  fi
fi

BACKUP_STAGE="$(mktemp -d "$BACKUP_OUTPUT_DIR/.stage-$BACKUP_TIMESTAMP.XXXXXX")"
BACKUP_ARCHIVE="$BACKUP_OUTPUT_DIR/uniemployee-$BACKUP_TIMESTAMP-$$.tar.gz"
BACKUP_TMP_ARCHIVE="$BACKUP_ARCHIVE.tmp"
cleanup() {
  rm -rf "$BACKUP_STAGE"
  rm -f "$BACKUP_TMP_ARCHIVE"
}
trap cleanup EXIT
mkdir -p "$BACKUP_STAGE/pg"

for db in "${BACKUP_DBS[@]}"; do
  full="${BACKUP_DB_PREFIX}${db}"
  echo "[$(date '+%F %T')] pg_dump $full"
  if [ -n "$BACKUP_PG_CONTAINER" ]; then
    if ! docker exec "$BACKUP_PG_CONTAINER" pg_dump -U "$BACKUP_PG_USER" -Fc "$full" \
        > "$BACKUP_STAGE/pg/$db.dump"; then
      echo "数据库 $full 导出失败，备份未生成" >&2
      exit 1
    fi
  elif ! PGPASSWORD="$BACKUP_PG_PASSWORD" "$BACKUP_PGDUMP" \
      -h "$BACKUP_PG_HOST" -p "$BACKUP_PG_PORT" -U "$BACKUP_PG_USER" \
      -Fc -f "$BACKUP_STAGE/pg/$db.dump" "$full"; then
    echo "数据库 $full 导出失败，备份未生成" >&2
    exit 1
  fi
done

if [ "${BACKUP_QUIESCED:-0}" = "1" ]; then
  BACKUP_CONSISTENCY="writes_paused_by_operator"
else
  BACKUP_CONSISTENCY="online_uncoordinated"
fi
{
  echo "format=uniemployee-backup-v2"
  echo "created_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "source_db_prefix=$BACKUP_DB_PREFIX"
  echo "databases=${BACKUP_DBS[*]}"
  echo "workspace_entry=workspace"
  echo "consistency=$BACKUP_CONSISTENCY"
} > "$BACKUP_STAGE/manifest.txt"

tar -czf "$BACKUP_TMP_ARCHIVE" \
  -C "$BACKUP_STAGE" manifest.txt pg \
  -C "$(dirname "$BACKUP_WORKSPACE_DIR")" workspace
tar -tzf "$BACKUP_TMP_ARCHIVE" >/dev/null
mv "$BACKUP_TMP_ARCHIVE" "$BACKUP_ARCHIVE"
echo "[$(date '+%F %T')] 备份完成：$BACKUP_ARCHIVE ($BACKUP_CONSISTENCY)"

if [ "$BACKUP_KEEP" -gt 0 ]; then
  ls -1t "$BACKUP_OUTPUT_DIR"/uniemployee-*.tar.gz 2>/dev/null \
    | tail -n +$((BACKUP_KEEP + 1)) \
    | while read -r old; do
        echo "[$(date '+%F %T')] 删除旧备份 $old"
        rm -f "$old"
      done
fi
