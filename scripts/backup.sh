#!/usr/bin/env bash
# UniEmployee 数据库备份脚本
# ---------------------------------------------------------------
# 把 catalog.db / conversations.db / checkpoints.db / store.db / traces.db
# 打包成带时间戳的 tar.gz 归档，并清理过旧的备份。
#
# 用法：
#   ./scripts/backup.sh [数据目录] [备份目录]
#
#   - 数据目录  默认 = 脚本所在目录的上级（即项目根，含 *.db）
#   - 备份目录  默认 = 数据目录/backups
#   - 保留份数  由环境变量 BACKUP_KEEP 控制（默认 7，设 0 表示不清理）
#
# 建议：定时任务里每天凌晨跑一次，例如
#   crontab -e  ->  0 3 * * * /path/to/scripts/backup.sh >> /var/log/uniemployee-backup.log 2>&1
#
# 注意：SQLite 有 -wal/-shm 临时文件。为获得一致性快照，建议在备份前
# 短暂停止服务（或确保无写入）；否则直接拷 .db 可能落在未 checkpoint 的状态。
# 若是挂载了同一份数据的从库 / 只读副本则更稳。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/.."
DATA_DIR="${1:-$PROJECT_DIR/data/db}"
BACKUP_DIR="${2:-$PROJECT_DIR/backups}"
KEEP="${BACKUP_KEEP:-7}"
TS="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$BACKUP_DIR/uniemployee-$TS.tar.gz"

DBS="catalog.db conversations.db checkpoints.db store.db traces.db"

mkdir -p "$BACKUP_DIR"

FILES=()
for db in $DBS; do
  if [ -f "$DATA_DIR/$db" ]; then
    FILES+=("$db")
  fi
done

if [ "${#FILES[@]}" -eq 0 ]; then
  echo "[$(date '+%F %T')] 未找到任何数据库文件（目录: $DATA_DIR），跳过。"
  exit 1
fi

echo "[$(date '+%F %T')] 备份 ${FILES[*]} -> $ARCHIVE"
# 进入数据目录，仅打包存在的库文件
( cd "$DATA_DIR" && tar -czf "$ARCHIVE" "${FILES[@]}" )

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
