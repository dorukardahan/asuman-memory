---
name: pre-session-save
description: "Save critical context snapshot when session ends"
metadata:
  openclaw:
    emoji: "\U0001F4BE"
    events: ["command:new"]
    requires:
      config: ["workspace.dir"]
---

# Pre-Session Save Hook

Saves a context snapshot before a session ends (when `/new` is issued).
This preserves critical decisions, tasks, and themes that should survive
compaction or session transitions.

## What It Does

1. Reads recent messages from the ending session
2. Extracts key themes, decisions, and pending tasks
3. Saves to `workspace/memory/critical-context-snapshot.json`
4. Optionally captures high-importance items to the Memory API

## Note

Adapted from the original plan's `agent:memoryFlush` event (which doesn't
exist in OpenClaw internal hooks). Uses `command:new` instead, which fires
when users start a new session — effectively the same as "session ending".
