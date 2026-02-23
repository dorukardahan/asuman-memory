---
name: post-compaction-restore
description: "Two-phase compaction recovery: record compaction events, restore context on next bootstrap"
metadata:
  openclaw:
    emoji: "🔄"
    events: ["after_compaction", "agent:bootstrap"]
    requires:
      config: ["workspace.dir"]
---

# Post-Compaction Restore Hook

Two-phase hook for compaction recovery:

## Phase 1: after_compaction
Records that compaction happened by writing `memory/compaction-flag.json`
with metadata (messageCount, compactedCount, tokenCount).

## Phase 2: agent:bootstrap
If compaction flag is recent (< 2 hours), reads `critical-context-snapshot.json`
and injects as `COMPACTION_RECOVERY` bootstrap file with "continue naturally"
instruction.

## History
- Originally fired only on `agent:bootstrap` (misnamed, ran on every bootstrap)
- Refactored 2026-02-17 [S11] to correctly use `after_compaction` event
