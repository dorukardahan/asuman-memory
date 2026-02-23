---
name: subagent-complete
description: "Log and track sub-agent completions for observability"
metadata:
  openclaw:
    emoji: "🔔"
    events: ["subagent"]
    requires:
      config: ["workspace.dir"]
---

# Subagent Complete Hook

Tracks sub-agent lifecycle events — logs completions, errors, and runtime
metrics. Uses the `subagent:complete` event from PR #20268.

## What It Does

1. Logs every sub-agent completion to `${SUBAGENT_LOG_DIR}/subagent-completions.log` (default: `./logs/subagent-completions.log`)
2. Tracks runtime metrics (duration, success/error rate)
3. Sends error outcomes to Memory API for post-mortem analysis
