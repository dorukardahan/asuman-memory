#!/bin/bash
# Asuman Memory — Daily SQLite Backup
# Copies memory.sqlite to /root/.asuman/backups/memory-YYYY-MM-DD.sqlite
# Keeps last 7 daily backups, deletes older ones.
# Cron: 0 4 * * * /opt/asuman/whatsapp-memory/scripts/backup_db.sh

set -e

DB_PATH="/root/.asuman/memory.sqlite"
BACKUP_DIR="/root/.asuman/backups"
DATE=$(date +%Y-%m-%d)
BACKUP_FILE="${BACKUP_DIR}/memory-${DATE}.sqlite"
KEEP_DAYS=7

# Ensure backup directory exists
mkdir -p "${BACKUP_DIR}"

# Only run if DB exists
if [ ! -f "${DB_PATH}" ]; then
    echo "$(date -Iseconds) ERROR: Database not found at ${DB_PATH}" >&2
    exit 1
fi

# Use sqlite3 .backup for a safe online copy (WAL-safe)
if command -v sqlite3 &>/dev/null; then
    sqlite3 "${DB_PATH}" ".backup '${BACKUP_FILE}'"
else
    # Fallback: plain file copy
    cp "${DB_PATH}" "${BACKUP_FILE}"
fi

echo "$(date -Iseconds) Backup created: ${BACKUP_FILE} ($(du -h "${BACKUP_FILE}" | cut -f1))"

# Prune old backups (keep last KEEP_DAYS)
find "${BACKUP_DIR}" -name "memory-*.sqlite" -type f -mtime +${KEEP_DAYS} -delete 2>/dev/null || true

# Count remaining backups
COUNT=$(find "${BACKUP_DIR}" -name "memory-*.sqlite" -type f | wc -l)
echo "$(date -Iseconds) Backups retained: ${COUNT}"
