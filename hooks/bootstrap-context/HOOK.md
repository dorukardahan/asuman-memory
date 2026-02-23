---
name: bootstrap-context
description: "Inject memory recall and daily notes at session start"
metadata:
  openclaw:
    emoji: "\U0001F9E0"
    events: ["agent:bootstrap"]
    requires:
      config: ["workspace.dir"]
---

# Bootstrap Context Hook

Injects relevant memory context at the start of every agent session.

## What It Does

1. Calls the Agent Memory API (`/v1/recall`) to fetch recent memories
2. Reads today's and yesterday's daily notes from `workspace/memory/`
3. Pushes combined context as `SESSION_CONTEXT` bootstrap file

## Requirements

- Memory API running at `localhost:8787`
- Daily notes in `workspace/memory/YYYY-MM-DD*.md` format
