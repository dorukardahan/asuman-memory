# NoldoMem

> Long-term memory for AI agents. Named after the Noldor — Tolkien's elves renowned for deep knowledge and craft.

NoldoMem gives your AI agents persistent memory that works like real memory: important things are remembered, trivial things fade, and mistakes become lasting lessons.

One SQLite file, no Docker required, no cloud DB.

## Features

- **Ebbinghaus Decay** — Memories fade naturally over time, just like human memory
- **Behavioral Reinforcement** — Agents learn from past mistakes via lesson memories
- **Hybrid Search** — Semantic embeddings + BM25 keyword search for accurate recall
- **Per-Agent Isolation** — Each agent gets its own memory database
- **Memory Consolidation** — Old memories are compressed and merged automatically
- **Trust & Provenance** — Track where every memory came from
- **Pattern-to-Policy** — Repeated mistakes auto-escalate to behavioral rules
- **Prompt Injection Protection** — Built-in sanitization prevents memory poisoning
- **Two-Pass Reranking** — Fast primary + background quality reranker with async cache refresh
- **Knowledge Graph** — Entity extraction, typed relations, temporal facts with conflict detection
- **Turkish + English NLP** — Morphological analysis, temporal parsing, ASCII folding
- **Resilient Embedding** — Batch fallback, 3-retry with exponential backoff, text truncation

## Quick Start

```bash
git clone https://github.com/dorukardahan/noldo-memory.git
cd noldo-memory

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
# Edit .env: set OPENROUTER_API_KEY, AGENT_MEMORY_API_KEY

set -a; source .env; set +a
python -m agent_memory
```

The API starts on `http://127.0.0.1:8787`.

## Embedding Server

NoldoMem needs an embedding API compatible with the OpenAI `/v1/embeddings` format. Run locally (recommended) or use a cloud API.

### Hardware auto-detection

```bash
./scripts/detect-hardware.sh          # show recommendation
./scripts/detect-hardware.sh --json   # machine-readable output
./scripts/detect-hardware.sh --apply  # write settings to .env
```

### Model profiles

| Profile | Model | Size | Dimensions | Min RAM | Use Case |
|---------|-------|------|------------|---------|----------|
| **minimal** | EmbeddingGemma 300M | 314MB | 768 | 1-2GB | Raspberry Pi, $5 VPS |
| **light** | Qwen3-Embedding-0.6B | 610MB | 1024 | 2-4GB | Small VPS |
| **standard** | Qwen3-Embedding-4B | 4.0GB | 2560 | 4-8GB | Mid-range server |
| **heavy** | Qwen3-Embedding-8B | 8.1GB | 4096 | 12GB+ | Dedicated server |

### Local setup

```bash
# Install llama.cpp, download model, then:
llama-server --model Qwen3-Embedding-4B-Q8_0.gguf \
  --embedding --pooling last --host 0.0.0.0 --port 8090 \
  --ctx-size 8192 --batch-size 2048 --threads 12 --parallel 2
```

Set `OPENROUTER_BASE_URL=http://127.0.0.1:8090/v1` and `AGENT_MEMORY_DIMENSIONS=2560` in `.env`.

### Cloud API

```bash
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_API_KEY=your-key
AGENT_MEMORY_MODEL=openai/text-embedding-3-large
AGENT_MEMORY_DIMENSIONS=3072
```

### Dimension compatibility

Changing embedding dimensions requires re-embedding all memories:

```bash
.venv/bin/python scripts/reindex_embeddings.py
# Dry run: .venv/bin/python scripts/reindex_embeddings.py --dry-run
```

## API

```bash
# Store a memory
curl -X POST localhost:8787/v1/store \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"text": "User prefers dark mode", "agent": "main"}'

# Recall memories
curl -X POST localhost:8787/v1/recall \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"query": "user preferences", "agent": "main", "limit": 5}'
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/recall` | POST | Hybrid search (semantic + BM25 + recency + strength + importance) |
| `/v1/capture` | POST | Batch ingest messages (auto memory_type classification) |
| `/v1/store` | POST | Store a single memory |
| `/v1/rule` | POST | Store a rule/instruction (importance=1.0) |
| `/v1/forget` | DELETE | Delete by ID or query |
| `/v1/search` | GET | Interactive search (CLI/debug) |
| `/v1/pin` | POST | Pin a memory (protects from decay/gc/consolidation) |
| `/v1/unpin` | POST | Unpin a memory |
| `/v1/decay` | POST | Run Ebbinghaus strength decay |
| `/v1/consolidate` | POST | Deduplicate + archive stale memories |
| `/v1/compress` | POST | Summarize old long memories |
| `/v1/gc` | POST | Permanently purge old soft-deleted memories |
| `/v1/amnesia-check` | POST | Check memory coverage by topic list |
| `/v1/stats` | GET | Database statistics |
| `/v1/agents` | GET | List agent databases |
| `/v1/health` | GET | Basic health check |
| `/v1/health/deep` | GET | DB integrity, embedding probe, vectorless count, disk |
| `/v1/metrics` | GET | Operational metrics (JSON) |
| `/v1/metrics/prometheus` | GET | Prometheus text exposition format |
| `/v1/admin/rotate-key` | POST | Rotate API key |
| `/v1/export` | GET | Export memories as JSON |
| `/v1/import` | POST | Import memories from JSON |

All endpoints accept `?agent=<id>` for per-agent routing. Use `agent=all` for cross-agent operations.

## Search Architecture

```text
Query -> [Semantic (0.50)] -> sqlite-vec cosine
      -> [Keyword  (0.25)] -> FTS5 BM25 trigram
      -> [Recency  (0.10)] -> exp(-0.01 * days)
      -> [Strength (0.07)] -> Ebbinghaus retention
      -> [Importance(0.08)] -> write-time scoring
      |
      RRF fusion (k=60)
      |
      Primary reranker (MiniLM, top-10)
      |
      Background reranker (BGE-v2-m3, top-3, async cache update)
```

## Configuration

All configuration is environment-driven. See `.env.example` for the full list.

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | `""` | Embedding API key |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Embedding API base URL |
| `AGENT_MEMORY_MODEL` | `qwen/qwen3-embedding-4b` | Embedding model name |
| `AGENT_MEMORY_DIMENSIONS` | `2560` | Embedding dimensions |
| `AGENT_MEMORY_DB` | `$HOME/.agent-memory/memory.sqlite` | SQLite path |
| `AGENT_MEMORY_HOST` | `127.0.0.1` | API bind address |
| `AGENT_MEMORY_PORT` | `8787` | API port |
| `AGENT_MEMORY_API_KEY` | `""` | API authentication key |
| `AGENT_MEMORY_RERANKER_ENABLED` | `true` | Enable cross-encoder reranker |
| `AGENT_MEMORY_EMBED_WORKER_ENABLED` | `true` | Background embed worker |

## Hooks

OpenClaw hook examples for NoldoMem integration are in [`hooks/`](./hooks/):

| Hook | Purpose |
|------|---------|
| `realtime-capture` | Capture messages in real-time |
| `session-end-capture` | Batch capture on session end |
| `bootstrap-context` | Inject recalled memories into context |
| `after-tool-call` | Capture tool results |
| `pre-session-save` | Tag sessions with memory metadata |
| `post-compaction-restore` | Restore context after compaction |
| `subagent-complete` | Capture sub-agent results |

See [`hooks/README.md`](./hooks/README.md) for setup instructions.

## Cron Jobs

See `crontab.example` for recommended schedules (decay, consolidation, GC, backfill, backup).

## Deployment

### NoldoMem API service

```bash
sudo cp agent-memory.service.example /etc/systemd/system/agent-memory.service
# Edit paths and EnvironmentFile
sudo systemctl daemon-reload
sudo systemctl enable --now agent-memory
```

### OpenClaw integration

Disable built-in memory in `openclaw.json`:

```json
{ "memorySearch": { "enabled": false } }
```

### Production checklist

- [ ] Strong secrets for `OPENROUTER_API_KEY`, `AGENT_MEMORY_API_KEY`
- [ ] `AGENT_MEMORY_HOST=127.0.0.1` (localhost only)
- [ ] Embedding server running (local or cloud)
- [ ] Cron jobs installed
- [ ] Hooks configured
- [ ] SQLite backup scheduled

## Docker

```bash
git clone https://github.com/dorukardahan/noldo-memory.git && cd noldo-memory
cp .env.example .env
mkdir -p models
wget -P models https://huggingface.co/Qwen/Qwen3-Embedding-4B-GGUF/resolve/main/Qwen3-Embedding-4B-Q8_0.gguf
docker compose up -d
curl http://localhost:8787/v1/health
```

## Tests

```bash
pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -x -q
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
