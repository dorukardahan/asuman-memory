# NoldoMem Hermes MemoryProvider

This adapter lets Hermes Agent use NoldoMem through Hermes' native
`MemoryProvider` contract.

## Install

Copy this directory into a Hermes profile:

```bash
mkdir -p "$HERMES_HOME/plugins/noldomem"
rsync -a adapters/hermes/noldomem/ "$HERMES_HOME/plugins/noldomem/"
```

Set Hermes memory config:

```yaml
memory:
  provider: noldomem
  memory_enabled: false
  user_profile_enabled: false
```

This makes NoldoMem the long-term memory source and prevents Hermes'
`MEMORY.md` / `USER.md` prompt injection from drifting away from the semantic
store. Keep `session_search` enabled if you still want transcript search.

Hermes v0.19 injects external `MemoryProvider` tools only when the effective
toolsets are unset or include `memory`. If your platform/profile uses an
explicit toolset list, keep `memory` enabled and verify that `noldomem_recall`,
`noldomem_store`, and `noldomem_pin` appear in the live tool surface. Builds
that expose `memory.external_tools_enabled_when_memory_toolset_disabled` may
use that explicit compatibility option instead. Use a distinct `agent` value
for each Hermes identity rather than sharing the legacy `hermes` scope.

## Configure

Create `$HERMES_HOME/noldomem.json`:

```json
{
  "base_url": "http://127.0.0.1:8787",
  "api_key_file": "/path/to/noldomem-api-key",
  "agent": "hermes-dorry",
  "namespace": "default",
  "recall_limit": 5,
  "recall_max_chars": 3500,
  "timeout_seconds": 8.0,
  "prefetch_enabled": true,
  "sync_prefetch_on_miss": true,
  "sync_turns_enabled": false,
  "tools_enabled": true,
  "recall_cache_ttl_seconds": 300.0,
  "recall_cache_max_entries": 128
}
```

Secrets can also be supplied through `NOLDOMEM_API_KEY` or
`NOLDOMEM_API_KEY_FILE`. Do not put secrets in committed config files.

## Tools

The provider exposes:

- `noldomem_recall`
- `noldomem_store`
- `noldomem_pin`

The provider also tracks Hermes session rotations. Store calls include the
current Hermes `session_id`, and NoldoMem preserves that value as
`source_session`.

The provider degrades silently when NoldoMem is unavailable. User replies should
not block on memory backend outages.

## Lifecycle and cache behavior

Hermes v0.19 runs `queue_prefetch` and `sync_turn` in its host-owned background
executor. The adapter performs those operations synchronously inside that lane
and does not create a nested thread per turn. The explicit `noldomem_store` tool
also remains synchronous: one tool call performs one direct store and returns
the backend result.

Hermes invokes `on_memory_write` inline for successful built-in memory writes,
so that compatibility hook is synchronous too. The adapter owns no worker
threads, queues, or pending-operation registry: a hook returns only after its
single bounded HTTP operation finishes. Shutdown marks the provider as closing
before waiting, rejects queued or late hooks, and applies one five-second
monotonic deadline to an already-running inline hook. Because Python cannot
force-stop an external caller thread, that caller may finish after the shutdown
deadline, but its HTTP operation remains bounded by `timeout_seconds`.

Recall results use a thread-safe LRU cache. `recall_cache_ttl_seconds` controls
expiry and `recall_cache_max_entries` controls the maximum entry count. The
cache is cleared on session changes, reset, Hermes `rewound=True` notifications,
legacy rewind reasons, and compaction boundaries.

Both cache settings are validated. Supported ranges are:

- `recall_cache_ttl_seconds`: 0.1–3600 seconds
- `recall_cache_max_entries`: 1–4096

Equivalent environment variables are available with the `NOLDOMEM_` prefix,
for example `NOLDOMEM_RECALL_CACHE_MAX_ENTRIES`.

## Diagnostics and readiness

Availability and tool discovery are configuration-only and never contact the
backend. The default doctor command follows the same rule:

```bash
python adapters/hermes/noldomem/doctor.py
```

It reports only safe booleans and endpoint classifications. It does not print
the endpoint host/path, API key, agent, namespace, response body, raw exception
text, or memory content.

Use `--live` only when an explicit bounded readiness read is wanted:

```bash
python adapters/hermes/noldomem/doctor.py --live --timeout 2
```

The timeout is capped at two seconds and enforced as one outer wall deadline on
POSIX main-thread calls, in addition to the transport timeout. If that deadline
cannot be installed safely (for example, from a non-main thread), the probe
fails closed without making a network call. The response body is size-bounded,
and only the health status, storage/embedding booleans, numeric uptime, and an
allowlisted error class are exposed. Exit codes are `0` for configured/default
or live-ready, `1` for unconfigured, and `2` for a completed or safely refused
live probe that is not ready.
