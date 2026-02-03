# Asuman Memory System

Production-ready conversational memory for **Asuman** — an AI assistant on [OpenClaw](https://openclaw.com) that speaks Turkish + English via WhatsApp.

Indexes every OpenClaw session into a searchable database with **semantic (vector) + keyword (BM25) + recency** hybrid search, powered by a single SQLite file.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                   FastAPI  (:8787)                        │
│  /v1/recall  /v1/capture  /v1/store  /v1/forget          │
│  /v1/search  /v1/stats    /v1/health                     │
└──────────┬──────────┬──────────┬─────────────────────────┘
           │          │          │
     ┌─────▼─────┐ ┌──▼───┐ ┌───▼───┐
     │  Hybrid   │ │Ingest│ │Entity │
     │  Search   │ │      │ │Extract│
     │(RRF Fuse) │ │JSONL │ │ KG    │
     └──┬──┬──┬──┘ └──┬───┘ └───┬───┘
        │  │  │        │         │
   ┌────▼┐ │ ┌▼────┐ ┌▼─────────▼─┐
   │Vec  │ │ │FTS5 │ │   SQLite   │
   │Srch │ │ │BM25 │ │ (storage)  │
   └──┬──┘ │ └──┬──┘ └─────┬──────┘
      │    │    │           │
      └────┴────┴───────────┘
         sqlite-vec + FTS5
         single .sqlite file

   ┌────────────┐   ┌──────────┐
   │ OpenRouter │   │  Turkish │
   │ Embeddings │   │   NLP    │
   │ qwen3-8b   │   │(zeyrek + │
   │ 4096d      │   │dateparser)│
   └────────────┘   └──────────┘
```

### Data Flow

1. **Ingest** — OpenClaw JSONL session files are parsed → chunked into Q&A pairs → MD5 deduped
2. **Embed** — Chunks are batch-embedded via OpenRouter (qwen3-embedding-8b, 4096 dim)
3. **Store** — Vectors + metadata go into SQLite (sqlite-vec for ANN, FTS5 for BM25)
4. **Search** — Queries hit 3 layers (semantic, keyword, recency) fused via Reciprocal Rank Fusion (RRF)
5. **Entities** — Regex + heuristic NER extracts people, places, orgs, tech terms → knowledge graph

### Modules

| Module | Description |
|--------|-------------|
| `config.py` | Environment-based configuration with JSON overlay |
| `embeddings.py` | OpenRouter embedding client — async, batched, cached, retries |
| `storage.py` | SQLite + sqlite-vec + FTS5 — memories, entities, relationships |
| `search.py` | 3-layer hybrid search with RRF fusion |
| `turkish.py` | Turkish NLP: zeyrek lemmatization, dateparser, ASCII folding, stopwords |
| `triggers.py` | Memory trigger patterns + importance scoring (0.0–1.0) |
| `entities.py` | Regex + heuristic NER → knowledge graph |
| `ingest.py` | Session JSONL parser → chunker → batch embedder |
| `api.py` | FastAPI HTTP API (7 endpoints) |

## Quick Start

```bash
# Clone
git clone https://github.com/dorukardahan/asuman-memory.git
cd whatsapp-memory

# Create venv and install
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set API key
export OPENROUTER_API_KEY="sk-or-..."

# Start API
python -m asuman_memory

# Health check
curl http://localhost:8787/v1/health
```

### Systemd Service

```bash
# Enable and start
sudo systemctl enable asuman-memory
sudo systemctl start asuman-memory

# Check status
sudo systemctl status asuman-memory
```

### Initial Data Load

```bash
# Load all session files
python scripts/initial_load.py

# Incremental sync (cron runs this every 30 min)
python scripts/openclaw_sync.py
```

## API Documentation

Interactive Swagger UI is available at **http://localhost:8787/docs** when the service is running.

### `GET /v1/health`

Health check with uptime and memory count.

**Response:**
```json
{
  "status": "ok",
  "uptime_seconds": 3621.5,
  "storage": true,
  "embedder": true,
  "total_memories": 218,
  "entities": 138
}
```

### `POST /v1/recall`

Search memories using hybrid search (semantic + BM25 + recency). The primary search endpoint.

**Request:**
```json
{
  "query": "memory system araştırması",
  "limit": 5,
  "min_score": 0.0
}
```

**Response:**
```json
{
  "query": "memory system araştırması",
  "count": 3,
  "triggered": true,
  "results": [
    {
      "id": "a1b2c3d4e5f6",
      "text": "User: memory sistemi nasıl çalışıyor?\nAssistant: ...",
      "category": "qa_pair",
      "importance": 0.75,
      "created_at": 1706900000.0,
      "score": 0.0158,
      "semantic_score": 0.8432,
      "keyword_score": 0.0,
      "recency_score": 0.9812,
      "confidence_tier": "MEDIUM"
    }
  ]
}
```

The `triggered` field indicates whether the query would naturally trigger a memory lookup (based on Turkish/English trigger patterns). Useful for deciding when to auto-recall.

### `POST /v1/capture`

Ingest a batch of messages into memory. Each message gets importance-scored, embedded, and stored.

**Request:**
```json
{
  "messages": [
    {"text": "User ile yarın toplantı var", "role": "user", "session": "abc123"},
    {"text": "Tamam, hatırlatırım.", "role": "assistant"}
  ]
}
```

**Response:**
```json
{
  "stored": 2,
  "total": 2
}
```

### `POST /v1/store`

Manually store a single memory (e.g., a fact, decision, or note).

**Request:**
```json
{
  "text": "User'ın favori rengi mavi",
  "category": "fact",
  "importance": 0.9
}
```

**Response:**
```json
{
  "id": "f7e8d9c0b1a2",
  "stored": true
}
```

### `DELETE /v1/forget`

Delete a memory by ID or by searching for it.

**Request (by ID):**
```json
{
  "id": "f7e8d9c0b1a2"
}
```

**Request (by query):**
```json
{
  "query": "favori rengi"
}
```

**Response:**
```json
{
  "deleted": true,
  "id": "f7e8d9c0b1a2"
}
```

### `GET /v1/search?query=X&limit=5`

Interactive search endpoint (for CLI/debug use). Same hybrid search as `/v1/recall` but via GET.

**Response:**
```json
{
  "query": "Python",
  "count": 3,
  "results": [...]
}
```

### `GET /v1/stats`

Database statistics.

**Response:**
```json
{
  "total_memories": 218,
  "by_category": {
    "qa_pair": 150,
    "user": 45,
    "assistant": 23
  },
  "entities": 138,
  "relationships": 95,
  "temporal_facts": 12
}
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | *(required)* | OpenRouter API key for embeddings |
| `ASUMAN_MEMORY_DB` | `~/.asuman/memory.sqlite` | SQLite database path |
| `ASUMAN_MEMORY_MODEL` | `qwen/qwen3-embedding-8b` | Embedding model name |
| `ASUMAN_MEMORY_PORT` | `8787` | API server port |
| `ASUMAN_MEMORY_HOST` | `0.0.0.0` | API bind address |
| `ASUMAN_MEMORY_DIMENSIONS` | `4096` | Vector dimensions |
| `ASUMAN_SESSIONS_DIR` | `~/.openclaw/agents/main/sessions` | Session JSONL directory |
| `ASUMAN_MEMORY_CONFIG` | *(none)* | Path to JSON config overlay |

### JSON Config File

Optionally, set `ASUMAN_MEMORY_CONFIG` to a JSON file to override any `Config` field:

```json
{
  "weight_semantic": 0.50,
  "weight_keyword": 0.30,
  "weight_recency": 0.20,
  "chunk_gap_hours": 4.0,
  "batch_size": 50
}
```

## Turkish NLP Features

### Lemmatization (zeyrek)

Turkish morphological analysis strips inflectional suffixes to root forms:

- `hatırlıyorum` → `hatırla` (remember)
- `çalışıyorsunuz` → `çalış` (work)
- `konuşmuştuk` → `konuş` (talk)

### ASCII Folding

Turkish special characters are folded for fuzzy matching:

- `çalışıyor` → `calisiyor`
- `ÇAĞRI` → `CAGRI`
- `güzel` → `guzel`

Both the original and folded forms are indexed for maximum recall.

### Temporal Parsing (dateparser)

Parses Turkish and English time expressions:

- `geçen hafta` → last 7 days
- `dün akşam` → yesterday evening
- `öbür gün` → day after tomorrow
- `evvelsi gün` → two days ago
- Standard dateparser expressions (yesterday, last month, etc.)

### Turkish Stopwords

75+ Turkish and English stopwords are removed during normalization (ve, bir, bu, the, a, is, ...).

### Trigger Detection

Intelligent detection of when a query needs memory context:

- **Turkish triggers:** `hatırl-`, `ne konuştuk`, `geçen`, `karar`, `unutma`, ...
- **English triggers:** `remember`, `last time`, `what did we say`, ...
- **Anti-triggers:** greetings, single emojis, okays (skipped for efficiency)
- **Past tense heuristic:** `-mıştı`, `-dık`, `was`, `did`, ...

## Backup & Maintenance

### Automatic Backups

Daily at 04:00, `scripts/backup_db.sh` creates a timestamped copy of the database:

```
/root/.asuman/backups/memory-2026-02-03.sqlite
```

Last 7 daily backups are kept; older ones are pruned automatically.

### Log Rotation

`/etc/logrotate.d/asuman-memory` handles weekly rotation of sync logs (4 weeks, compressed).

### Management Script

```bash
./scripts/manage.sh status    # Service + API + DB stats
./scripts/manage.sh logs 100  # Follow journal logs
./scripts/manage.sh sync      # Incremental session sync
./scripts/manage.sh load      # Full data load
./scripts/manage.sh health    # Quick health check
./scripts/manage.sh restart   # Restart the API service
```

### Manual Sync

```bash
# Incremental sync (only new sessions)
./scripts/manage.sh sync

# Full reload (re-scan all sessions)
./scripts/manage.sh sync --full

# Store without embeddings (faster, no API calls)
./scripts/manage.sh sync --skip-embeddings
```

## Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run all tests
pytest tests/ -v

# Run specific module tests
pytest tests/test_api.py -v
pytest tests/test_turkish.py -v
```

Test coverage includes:
- **Embeddings** — mock API, batch embed, retry logic, LRU cache
- **Storage** — CRUD, vector search, FTS5, entities, batch ops
- **Search** — RRF fusion, weight config, hybrid search
- **Turkish NLP** — lemmatization, ASCII folding, stopwords, temporal parsing
- **Triggers** — Turkish/English triggers, anti-triggers, importance scoring
- **Entities** — extraction, dedup, knowledge graph relationships
- **Ingest** — session parsing, chunking, MD5 dedup, filtering
- **API** — all 7 HTTP endpoints + OpenAPI docs

## Dependencies

Total install size < 25 MB. No torch, no transformers, no heavy ML.

```
requests, numpy, sqlite-vec, dateparser, zeyrek
fastapi, uvicorn, pydantic
```

## License

MIT
