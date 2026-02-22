# Features

## v0.3.0 (Current)

### Search
- 5-layer hybrid search: semantic + BM25 keyword + recency + strength + importance
- Reciprocal Rank Fusion (RRF) with k=60
- Two-pass cross-encoder reranking (primary: balanced/MiniLM, background: quality/BGE-v2-m3)
- Temporal-aware search: parses time expressions ("yesterday", "last week", "3 days ago")
- Cross-agent search (`agent=all`)
- Result caching with TTL

### Storage
- SQLite + sqlite-vec for vector storage (cosine distance)
- FTS5 with trigram tokenizer for keyword search
- Per-agent database isolation (StoragePool)
- Write-time semantic merge (cosine ≥ 0.85 dedup)
- Soft-delete with permanent GC

### Embedding
- Any OpenAI-compatible embedding API (local llama.cpp or cloud)
- 3-tier caching: LRU in-memory → SQLite persistent → API call
- Resilient batch embedding with individual fallback
- Configurable text truncation (`max_embed_chars`)
- Vectorless backfill script for failed embeddings
- 3-retry with exponential backoff

### Knowledge Graph
- Regex-based entity extraction (names, phones, emails, dates, tech terms)
- 12 typed relation categories
- Temporal facts with validity periods
- Conflict detection for exclusive relations (lives_in, works_at, status)
- Auto-resolution with confidence margin

### NLP (Turkish + English)
- Morphological analysis via zeyrek (Turkish lemmatization)
- Temporal expression parsing (dateparser + custom Turkish patterns)
- ASCII folding (ç→c, ğ→g, ı→i, ö→o, ş→s, ü→u)
- 70+ Turkish stopwords
- Trigger detection: 30+ Turkish + 15+ English patterns

### Memory Lifecycle
- Ebbinghaus spaced-repetition decay (importance-adjusted)
- Consolidation: union-find merge for similar memories
- GC: soft-delete weak/stale memories, permanent purge after 30 days
- Importance scoring: decision markers, conversation detection, cron output capping

### Security
- API key authentication (constant-time compare)
- Rate limiting: 120 req/min per IP (sliding window)
- Audit logging to file
- CORS: localhost-only
- Health endpoint: auth-free

### API
- FastAPI with Pydantic models
- Export/Import endpoints for backup and migration
- Per-agent routing (`?agent=<id>`)
- Cross-agent operations (`agent=all`)
- Centralized error handling with JSON responses

### Scripts
- `openclaw_sync.py` — incremental session sync with state tracking
- `backfill_vectors.py` — embed vectorless memories (cron-friendly)
- `rescore_cron_memories.py` — recalibrate importance scores for automated content
- `backup_db.sh` — daily SQLite backup
- `export-to-workspace.py` — export highlights to workspace files
