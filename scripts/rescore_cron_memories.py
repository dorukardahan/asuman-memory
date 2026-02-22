#!/usr/bin/env python3
import os
import re
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("AGENT_MEMORY_DB", str(Path.home() / ".agent-memory" / "memory.sqlite"))

CRON_PATTERNS = [
    re.compile(r"^\[cron:", re.IGNORECASE),
    # Add your own cron output patterns to detect low-importance automated messages:
    # re.compile(r"my-cron-job", re.IGNORECASE),
    re.compile(r"HEARTBEAT_OK", re.IGNORECASE),
    re.compile(r"Return your summary as plain text", re.IGNORECASE),
]

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT id, text, importance FROM memories WHERE deleted_at IS NULL").fetchall()
updated = 0
for r in rows:
    text = r["text"] or ""
    imp = float(r["importance"] or 0.5)
    if any(p.search(text) for p in CRON_PATTERNS) and imp > 0.30:
        conn.execute("UPDATE memories SET importance = 0.30 WHERE id = ?", (r["id"],))
        updated += 1
conn.commit()
print(f"processed={len(rows)} updated={updated}")
