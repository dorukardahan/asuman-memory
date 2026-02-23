#!/bin/bash
# ./scripts/backup_db.sh
# OpenClaw Memory — SQLite backup helper (v2: per-agent + config)
# Creates safe online backups (WAL-safe) and prunes older backups.
# Cron: 0 7 * * * ./scripts/backup_db.sh

set -euo pipefail

MEMORY_DIR="${AGENT_MEMORY_DATA_DIR:-${HOME}/.asuman}"
BACKUP_DIR="${MEMORY_DIR}/backups"
CONFIG_FILE="${HOME}/.openclaw/openclaw.json"
DATE=$(date +%Y-%m-%d)
KEEP_DAYS="${OPENCLAW_MEMORY_BACKUP_KEEP_DAYS:-7}"

mkdir -p "${BACKUP_DIR}"

backed=0
errors=0

# Backup all memory*.sqlite files (main + per-agent)
for db in "${MEMORY_DIR}"/memory*.sqlite; do
    [ -f "$db" ] || continue
    basename=$(basename "$db" .sqlite)
    backup_file="${BACKUP_DIR}/${basename}-${DATE}.sqlite"

    if sqlite3 "$db" ".backup '${backup_file}'" 2>/dev/null; then
        size=$(du -h "${backup_file}" | cut -f1)
        echo "$(date -Iseconds) Backup: ${backup_file} (${size})"
        backed=$((backed + 1))
    else
        echo "$(date -Iseconds) ERROR: Failed to backup ${db}" >&2
        errors=$((errors + 1))
    fi
done

# Backup openclaw.json (weekly, on Sundays)
if [ "$(date +%u)" = "7" ] && [ -f "$CONFIG_FILE" ]; then
    config_backup="${BACKUP_DIR}/openclaw-${DATE}.json"
    cp "$CONFIG_FILE" "$config_backup"
    echo "$(date -Iseconds) Config backup: ${config_backup}"
fi

# Prune old backups (keep per retention policy)
find "${BACKUP_DIR}" -name "memory*-*.sqlite" -type f -mtime "+${KEEP_DAYS}" -delete 2>/dev/null || true
find "${BACKUP_DIR}" -name "openclaw-*.json" -type f -mtime "+30" -delete 2>/dev/null || true

COUNT=$(find "${BACKUP_DIR}" -type f | wc -l | tr -d ' ')
echo "$(date -Iseconds) Summary: ${backed} backed up, ${errors} errors, ${COUNT} files retained"
