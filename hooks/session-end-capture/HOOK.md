---
name: session-end-capture
description: "Capture session content on ANY session end (not just /new)"
metadata:
  openclaw:
    emoji: "📥"
    events: ["session_end"]
    requires:
      config: ["workspace.dir"]
---

# Session End Capture Hook

Captures session content when ANY session ends — including specialist agent
subagent sessions that complete without `/new`.

## Why This Exists

The `pre-session-save` hook only fires on `command:new`. Specialist agents
(spawned via `sessions_spawn`) complete and terminate without issuing `/new`.
This means their session content is NEVER captured to memory via hooks.

This hook uses `session_end` which fires on ALL session terminations:
- Subagent completion
- Idle timeout
- Daily reset
- Gateway restart

## What It Does

1. Reads last 15 messages from the ending session's JSONL file
2. Builds Q&A pairs for proper memory structure
3. Sends to Memory API `/v1/capture` with per-agent routing

## Requirements

- Memory API running at `localhost:8787`
