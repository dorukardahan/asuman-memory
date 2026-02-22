# Agent Memory

Persistent, local-first memory for AI agents. One SQLite file, no Docker, no cloud DB.

Your agent remembers conversations, decisions, and facts across sessions with hybrid recall.

## Features

- **5-layer hybrid search** — semantic (sqlite-vec) + BM25 keyword + recency + strength + importance, fused with Reciprocal Rank Fusion (k=60)
- **Two-pass cross-encoder reranking** — fast primary reranker + background quality reranker with async cache refresh
- **Knowledge graph** — entity extraction, typed relations, temporal facts with conflict detection
- **Ebbinghaus decay** — spaced-repetition strength model with importance-adjusted curves
- **Turkish + English NLP** — morphological analysis (zeyrek), temporal parsing, ASCII folding, stopwords
- **Per-agent isolation** — each agent gets its own SQLite database, cross-agent search supported
- **Write-time semantic merge** — deduplicates similar memories at ingest (cosine ≥ 0.85)
- **Consolidation & GC** — periodic dedup, weak memory archival, permanent purge of old soft-deletes
- **Resilient embedding** — batch fallback to individual, 3-retry with exponential backoff, text truncation
- **Vectorless backfill** — cron script to embed memories that failed initial embedding
- **Security** — API key auth, rate limiting (120 req/min), audit logging, localhost-only CORS
- **Export/Import** — JSON export/import for backup and migration

## Quick Start

```bash
# Clone
git clone https://github.com/dorukardahan/asuman-memory.git
cd asuman-memory

# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure (create .env)
cat > .env << EOF
OPENROUTER_API_KEY=your-key-here
OPENROUTER_BASE_URL=http://localhost:8090/v1  # or https://openrouter.ai/api/v1
AGENT_MEMORY_DB=/path/to/memory.sqlite
AGENT_MEMORY_DIMENSIONS=2560
AGENT_MEMORY_API_KEY=your-api-key
AGENT_MEMORY_RERANKER_ENABLED=true
AGENT_MEMORY_RERANKER_MODEL=balanced
EOF

# Run
source .env
python -m agent_memory
```

The API starts on `http://127.0.0.1:8787`.

## Embedding Server

Agent Memory needs an embedding API compatible with the OpenAI `/v1/embeddings` format. Options:

**Local (recommended for privacy):**
```bash
# llama.cpp with Qwen3-Embedding
llama-server --model Qwen3-Embedding-4B-Q8_0.gguf \
  --embedding --pooling last --host 0.0.0.0 --port 8090 \
  --ctx-size 8192 --batch-size 2048 --threads 12 --parallel 2
```

**Cloud:**
Set `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1` and use any embedding model.

> **Important:** With `--parallel N`, each slot gets `ctx-size / N` tokens. Set `ctx-size` high enough for your longest texts, or use `AGENT_MEMORY_MAX_EMBED_CHARS` to truncate.

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/recall` | POST | Hybrid search (semantic + BM25 + recency + strength + importance) |
| `/v1/capture` | POST | Batch ingest messages |
| `/v1/store` | POST | Store a single memory |
| `/v1/rule` | POST | Store a rule/instruction (importance=1.0) |
| `/v1/forget` | DELETE | Delete by ID or query |
| `/v1/search` | GET | Interactive search (CLI/debug) |
| `/v1/decay` | POST | Run Ebbinghaus strength decay |
| `/v1/consolidate` | POST | Deduplicate + archive stale memories |
| `/v1/gc` | POST | Permanently purge old soft-deleted memories |
| `/v1/stats` | GET | Database statistics |
| `/v1/agents` | GET | List agent databases |
| `/v1/health` | GET | Health check with probes |
| `/v1/metrics` | GET | Operational metrics |
| `/v1/export` | GET | Export memories as JSON |
| `/v1/import` | POST | Import memories from JSON |

All endpoints accept `?agent=<id>` for per-agent routing. Use `agent=all` for cross-agent operations.

## Search Architecture

```
Query → [Semantic (0.50)] → sqlite-vec cosine
      → [Keyword  (0.25)] → FTS5 BM25 trigram
      → [Recency  (0.10)] → exp(-0.01 × days)
      → [Strength (0.07)] → Ebbinghaus retention
      → [Importance(0.08)] → write-time scoring
      ↓
      RRF fusion (k=60)
      ↓
      Primary reranker (MiniLM, top-10)
      ↓
      Background reranker (BGE-v2-m3, top-3, async cache update)
```

## Configuration

All config via environment variables (`AGENT_MEMORY_*` prefix):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | Embedding API key |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Embedding API URL |
| `AGENT_MEMORY_DB` | `~/.agent-memory/memory.sqlite` | Database path |
| `AGENT_MEMORY_DIMENSIONS` | `4096` | Embedding dimensions |
| `AGENT_MEMORY_PORT` | `8787` | API port |
| `AGENT_MEMORY_HOST` | `127.0.0.1` | API bind address |
| `AGENT_MEMORY_API_KEY` | — | API authentication key |
| `AGENT_MEMORY_MAX_EMBED_CHARS` | `3500` | Truncate text before embedding |
| `AGENT_MEMORY_RERANKER_ENABLED` | `true` | Enable cross-encoder reranking |
| `AGENT_MEMORY_RERANKER_MODEL` | `balanced` | Reranker preset: `fast`/`balanced`/`quality` |
| `AGENT_MEMORY_RERANKER_TWO_PASS_ENABLED` | `true` | Enable background quality reranker |

Legacy `ASUMAN_MEMORY_*` prefixes are also accepted.

## Cron Jobs

```bash
# Incremental session sync (every 30 min)
*/30 * * * * cd /path/to/agent-memory && . .env && venv/bin/python scripts/openclaw_sync.py

# Ebbinghaus decay (daily 2am)
0 2 * * * curl -s -X POST -H "X-API-Key: $KEY" http://localhost:8787/v1/decay -d '{"agent":"all"}'

# Consolidation (weekly Sunday 3am)
0 3 * * 0 curl -s -X POST -H "X-API-Key: $KEY" http://localhost:8787/v1/consolidate -d '{"agent":"all"}'

# GC purge (weekly Sunday 4am)
0 4 * * 0 curl -s -X POST -H "X-API-Key: $KEY" http://localhost:8787/v1/gc -d '{"agent":"all"}'

# Vectorless backfill (every 6 hours)
0 */6 * * * cd /path/to/agent-memory && . .env && venv/bin/python scripts/backfill_vectors.py --agent all
```

## Tests

```bash
venv/bin/python -m pytest tests/ -x -q
```

## License

MIT
