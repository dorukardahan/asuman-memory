#!/usr/bin/env bash
# Automated SQLite backup for NoldoMem
# Uses sqlite3 .backup for consistency (safe during WAL writes)
set -euo pipefail

# Auto-detect data dir (3-tier: env > ~/.agent-memory > ~/.noldomem)
DATA_DIR="${AGENT_MEMORY_DATA_DIR:-}"
if [ -z "$DATA_DIR" ]; then
    if [ -d "$HOME/.agent-memory" ]; then
        DATA_DIR="$HOME/.agent-memory"
    elif [ -d "$HOME/.noldomem" ]; then
        DATA_DIR="$HOME/.noldomem"
    else
        echo "ERROR: No data directory found" >&2
        exit 1
    fi
fi

BACKUP_DIR="${DATA_DIR}/backups"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-14}

mkdir -p "$BACKUP_DIR"

count=0
for db in "$DATA_DIR"/memory*.sqlite; do
    [ -f "$db" ] || continue
    name=$(basename "$db" .sqlite)
    dest="$BACKUP_DIR/${name}-${TIMESTAMP}.sqlite"
    sqlite3 "$db" ".backup '$dest'"
    # Compress
    gzip "$dest"
    count=$((count + 1))
done

# Prune old backups
find "$BACKUP_DIR" -name "memory*-*.sqlite.gz" -mtime "+$RETENTION_DAYS" -delete

echo "Backed up $count databases to $BACKUP_DIR (retention: ${RETENTION_DAYS}d)"
