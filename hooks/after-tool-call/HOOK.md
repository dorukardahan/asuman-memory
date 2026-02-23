---
name: after-tool-call
description: "Capture important tool execution results (deploys, git, config, errors) to memory"
metadata:
  openclaw:
    emoji: "🔧"
    events: ["after_tool_call"]
    requires:
      config: ["workspace.dir"]
---

# After Tool Call Hook

Captures operationally important tool outputs to the Memory API.

## What It Does

1. Fires after every tool call completes
2. Checks if the tool is `exec` and the command matches important patterns
3. Skips routine commands (ls, cat, grep, find, etc.)
4. Captures matching results to `/v1/store` with appropriate importance score

## Captured Event Types

- Service operations: systemctl restart/stop/start, docker compose up/down
- Git operations: push, merge, tag, commit
- Config changes: writes to .env, .conf, .service files
- Package management: apt/pip/npm install/upgrade
- Infrastructure: ufw, iptables, certbot
- Errors: any output containing error/fail/SIGKILL/OOM

## Requirements

- Memory API running at `localhost:8787`
