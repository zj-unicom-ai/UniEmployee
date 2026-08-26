#!/usr/bin/env bash
# UniEmployee 数据库备份脚本（PostgreSQL）
# ---------------------------------------------------------------
# 对 7 个业务库逐个 pg_dump（自定义格式 -Fc），打包成带时间戳的 tar.gz，
# 并清理过旧的备份。
#
# 用法：
#   ./scripts/backup.sh [备份目录]
#
#   - 备份目录  默认 = 项目根/backups
#   - 保留份数  由环境变量 BACKUP_KEEP 控制（默认 7，设 0 表示不清理）
#   - 连接参数从 .env 读取（POSTGRES_HOST/PORT/USER/PASSWORD/DB_PREFIX）
#   - 可用 PGBIN 指定 pg_dump 所在目录（如 /opt/homebrew/opt/postgresql@16/bin）
#
# 建议：定时任务里每天凌晨跑一次，例如
#   crontab -e  ->  0 3 * * * /path/to/scripts/backup.sh >> /var/log/uniemployee-backup.log 2>&1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/.."
BACKUP_DIR="${1:-$PROJECT_DIR/backups}"
KEEP="${BACKUP_KEEP:-7}"
TS="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$BACKUP_DIR/uniemployee-$TS.tar.gz"

# 从 .env 读 PG 连接参数
ENV_FILE="$PROJECT_DIR/.env"
HOST="127.0.0.1" PORT="5432" USER="uniemployee" PASSWORD="" PREFIX=""
if [ -f "$ENV_FILE" ]; then
  _env() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d ' \r' || true; }
  HOST="$(_env POSTGRES_HOST)"; HOST="${HOST:-127.0.0.1}"
  PORT="$(_env POSTGRES_PORT)"; PORT="${PORT:-5432}"
  USER="$(_env POSTGRES_USER)"; USER="${USER:-uniemployee}"
  PASSWORD="$(_env POSTGRES_PASSWORD)"
  PREFIX="$(_env POSTGRES_DB_PREFIX)"
fi

mkdir -p "$BACKUP_DIR"

PGDUMP="${PGBIN:+$PGBIN/}pg_dump"
if ! command -v "$PGDUMP" >/dev/null 2>&1; then
  echo "[$(date '+%F %T')] 找不到 pg_dump（可用 PGBIN=/path/to/bin 指定），"
  echo "  docker 部署可改用: docker exec -t uniemployee-pg pg_dump -U $USER <db>"
  exit 1
fi

DUMP_DIR="$BACKUP_DIR/pg-$TS"
mkdir -p "$DUMP_DIR"

DBS="catalog conversations checkpoints store traces approvals ontology"
dumped=()
for db in $DBS; do
  full="${PREFIX}${db}"
  echo "[$(date '+%F %T')] pg_dump $full"
  if PGPASSWORD="$PASSWORD" "$PGDUMP" -h "$HOST" -p "$PORT" -U "$USER" \
      -Fc -f "$DUMP_DIR/$full.dump" "$full" 2>/dev/null; then
    dumped+=("$full.dump")
  else
    echo "  [警告] $full 导出失败（库不存在？），跳过"
    rm -f "$DUMP_DIR/$full.dump"
  fi
done

if [ "${#dumped[@]}" -eq 0 ]; then
  echo "[$(date '+%F %T')] 没有任何库导出成功，退出。"
  rmdir "$DUMP_DIR" 2>/dev/null || true
  exit 1
fi

( cd "$DUMP_DIR" && tar -czf "$ARCHIVE" "${dumped[@]}" )
rm -rf "$DUMP_DIR"
echo "[$(date '+%F %T')] 备份 -> $ARCHIVE"

# 清理旧备份：按修改时间倒序，保留最近 KEEP 份
if [ "$KEEP" -gt 0 ]; then
  ls -1t "$BACKUP_DIR"/uniemployee-*.tar.gz 2>/dev/null \
    | tail -n +$((KEEP + 1)) \
    | while read -r old; do
        echo "[$(date '+%F %T')] 删除旧备份 $old"
        rm -f "$old"
      done
fi

echo "[$(date '+%F %T')] 完成。当前保留最近 $KEEP 份。"
ls -1ht "$BACKUP_DIR"/uniemployee-*.tar.gz 2>/dev/null | head -n "$KEEP"
