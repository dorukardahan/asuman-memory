# OpenClaw Hooks for Agent Memory

This directory contains **documented example hooks** used to integrate OpenClaw with the Agent Memory API.

> These are shipped as `handler.js.example` files on purpose. Rename/copy to `handler.js` in your OpenClaw hooks directory when you want to enable them.

## Hook Overview

| Hook | Trigger event(s) | What it does | Memory API endpoint |
|---|---|---|---|
| `realtime-capture` | `message_received` | Captures important user messages/decisions in real time | `POST /v1/store` |
| `session-end-capture` | `session_end` | Captures ending session messages (including subagents), builds QA pairs, writes `last-session.md` | `POST /v1/capture` |
| `bootstrap-context` | `agent:bootstrap` | Recalls recent memories and injects `SESSION_CONTEXT` on session start | `POST /v1/recall` |
| `after-tool-call` | `after_tool_call` | Captures operationally important `exec` outputs (deploy/git/config/errors) | `POST /v1/store` |
| `post-compaction-restore` | `after_compaction`, `agent:bootstrap` | Writes compaction flag and restores `COMPACTION_RECOVERY` bootstrap context | _No API call_ (filesystem snapshot restore) |
| `pre-session-save` | `command:new` | Saves critical context snapshot before a session reset/new | _No API call by default_ (optional `POST /v1/capture` helper exists) |
| `subagent-complete` | `subagent:complete` (`type=subagent`, `action=complete`) | Logs subagent completion/errors and stores failures for post-mortem | `POST /v1/capture` (error cases) |

---

## Directory Layout

Each hook directory contains:

- `HOOK.md` — OpenClaw hook metadata and behavior notes
- `handler.js.example` — sanitized example handler (safe placeholders)

```text
hooks/
  README.md
  after-tool-call/
    HOOK.md
    handler.js.example
  bootstrap-context/
    HOOK.md
    handler.js.example
  post-compaction-restore/
    HOOK.md
    handler.js.example
  pre-session-save/
    HOOK.md
    handler.js.example
  realtime-capture/
    HOOK.md
    handler.js.example
  session-end-capture/
    HOOK.md
    handler.js.example
  subagent-complete/
    HOOK.md
    handler.js.example
```

---

## Required Environment Variables

Set these where OpenClaw runs:

```bash
export MEMORY_API_URL="http://localhost:8787"
export MEMORY_API_KEY="your_agent_memory_api_key"
```

The example handlers use these defaults internally:

- `process.env.MEMORY_API_URL || "http://localhost:8787"`
- `process.env.MEMORY_API_KEY || "YOUR_MEMORY_API_KEY"`

Optional variables used by some hooks:

- `OPENCLAW_HOME` (default: `$HOME/.openclaw`)
- `OPENCLAW_WORKSPACE_DIR` (default: `/path/to/openclaw/workspace` in examples)
- `SUBAGENT_LOG_DIR` (default: `./logs`)

---

## Installation

1. **Copy hooks to your OpenClaw hook directory** (or keep them in-repo and point `extraDirs` there).
2. For each hook, copy `handler.js.example` to `handler.js`.
3. Add all hook directories to OpenClaw `hooks.internal.load.extraDirs`.
4. Restart OpenClaw gateway.

Example:

```bash
# from repo root
mkdir -p "$HOME/.openclaw/hooks"
cp -R hooks/* "$HOME/.openclaw/hooks/"

for d in "$HOME"/.openclaw/hooks/*; do
  cp "$d/handler.js.example" "$d/handler.js"
done
```

---

## Example OpenClaw Config Snippet

Add/update this in your OpenClaw config (for example `~/.openclaw/openclaw.json`):

```json
{
  "hooks": {
    "enabled": true,
    "internal": {
      "enabled": true,
      "load": {
        "extraDirs": [
          "/path/to/openclaw/hooks/bootstrap-context",
          "/path/to/openclaw/hooks/pre-session-save",
          "/path/to/openclaw/hooks/post-compaction-restore",
          "/path/to/openclaw/hooks/after-tool-call",
          "/path/to/openclaw/hooks/session-end-capture",
          "/path/to/openclaw/hooks/subagent-complete",
          "/path/to/openclaw/hooks/realtime-capture"
        ]
      }
    }
  }
}
```

Then restart:

```bash
openclaw gateway restart
```

---

## Notes

- These are **example hooks** for learning + setup guidance.
- Keep real secrets in environment variables, never in hook files.
- Do not commit active `handler.js` with production credentials.
