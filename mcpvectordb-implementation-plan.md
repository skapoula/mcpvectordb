# mcpvectordb — Implementation Plan

## What We're Building

An MCP server that gives Claude Desktop semantic search over a personal document library
organised into named collections. Documents (local files or URLs) are converted to Markdown,
chunked, embedded, and stored in a single LanceDB table partitioned by `library` field.
Claude Desktop queries via seven MCP tools over stdio (local) or SSE (k3s hosted).

---

## Architecture Decision Record

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Vector DB | LanceDB | Native updates/deletes, metadata filtering, no separate server process |
| Converter | `markitdown[all]` | Handles all formats + URLs uniformly, no separate httpx/BS4 layer |
| Chunking unit | Tokens | Accurate relative to embedding model context window |
| Tokenizer | `AutoTokenizer` from `nomic-ai/nomic-embed-text-v1.5` | Same tokenizer as embedding model; already available via `transformers` transitive dep |
| Embedding model | `nomic-embed-text-v1.5` (local) | Best open-source retrieval quality (MTEB ~62); no API dependency |
| Embedding interface | Two methods: `embed_documents` / `embed_query` | Nomic requires different prefixes per use; prevents silent quality degradation |
| Deduplication | SHA256 content hash | Skip unchanged files; delete-then-reinsert on change; stored in `ChunkRecord` |
| Singleton scope | Embedder only (not DB) | LanceDB opens in ~50ms; embedding model takes 5-10s; singleton only where it matters |
| Ingestion trigger | MCP tools only (push model) | No background threading complexity; watch folder deferred to v2 as separate CLI script |
| CLI output | Plain `logging` | No `rich` dependency; all logs to stderr (required for stdio MCP transport) |
| Multi-library model | Single table, `library` field as filter | Simpler than one table per library; cross-library search is free; free-form names (no pre-registration required) |
| Default library | Configurable via `DEFAULT_LIBRARY` in `.env` | Ingestion without explicit library name falls back to default |

---

## Components

Seven files under `src/mcpvectordb/`:

### `config.py`
- pydantic-settings; all values from `.env`
- Settings: `MCP_TRANSPORT`, `MCP_HOST`, `MCP_PORT`, `LANCEDB_URI`, `LANCEDB_TABLE_NAME`,
  `DEFAULT_LIBRARY`, `EMBEDDING_MODEL`, `EMBEDDING_BATCH_SIZE`, `CHUNK_SIZE_TOKENS`,
  `CHUNK_OVERLAP_TOKENS`, `CHUNK_MIN_TOKENS`, `HTTP_TIMEOUT_SECONDS`, `LOG_LEVEL`, `LOG_FILE`

### `converter.py`
- Thin `markitdown[all]` wrapper
- Accepts `Path` (local file) or `str` (URL)
- Dispatches by file extension for local files; passes URLs directly to MarkItDown
- Raises `UnsupportedFormatError(ext)` for unknown extensions — never silently ignores
- Reuses existing structure almost entirely; adds URL path and audio/image extensions

### `chunker.py`
- Reuses existing `Chunk` dataclass and `RecursiveCharacterTextSplitter` structure
- Replaces `length_function=len` with tokenizer token counting:
  ```python
  tokenizer = AutoTokenizer.from_pretrained("nomic-ai/nomic-embed-text-v1.5")
  length_function = lambda t: len(tokenizer.encode(t))
  ```
- `chunk_size` and `chunk_overlap` in tokens, from config
- Preserves section header metadata per chunk

### `embedder.py`
- `nomic-embed-text-v1.5` via `sentence-transformers`, local only
- Two public methods:
  - `embed_documents(texts: list[str]) -> NDArray[float32]` — prepends `"search_document: "`
  - `embed_query(query: str) -> NDArray[float32]` — prepends `"search_query: "`
- Loaded once at server startup; reused across all requests via singleton in `server.py`
- Batch size configurable via `EMBEDDING_BATCH_SIZE`

### `store.py`
- LanceDB read/write; connection opens per-call (~50ms, no singleton needed)
- **Schema (`ChunkRecord`):**

  | Field | Type | Notes |
  |-------|------|-------|
  | `id` | `str` | uuid4, chunk-level unique ID |
  | `doc_id` | `str` | uuid4, groups all chunks from one source |
  | `library` | `str` | collection name; defaults to `DEFAULT_LIBRARY` from config |
  | `source` | `str` | original file path or URL |
  | `content_hash` | `str` | SHA256 of raw source content, for deduplication |
  | `title` | `str` | inferred or user-supplied |
  | `content` | `str` | Markdown chunk text |
  | `embedding` | `list[float]` | nomic vector (768d) |
  | `chunk_index` | `int` | position within document |
  | `created_at` | `str` | ISO 8601 |
  | `metadata` | `str` | JSON-serialised user key-value pairs |

- **Key operations:** `upsert_chunks`, `search`, `get_document`, `list_documents`, `delete_document`, `list_libraries`
- **Deduplication flow:**
  1. Compute SHA256 of raw file bytes / URL response body before converting
  2. Query: does any chunk with this `source` exist?
  3. If yes and `content_hash` matches → skip (return `skipped=True`)
  4. If yes and hash differs → delete all chunks for `doc_id`, then re-ingest
  5. If no → ingest fresh

### `ingestor.py`
- Orchestrates the full pipeline:
  ```
  input (Path | URL, library)
    → read raw bytes / fetch URL
    → SHA256 hash → dedup check (store.py, scoped to library)
    → convert to Markdown (converter.py)
    → chunk (chunker.py)
    → embed chunks (embedder.py)
    → upsert with library tag (store.py)
  ```
- Returns `IngestResult`: `doc_id`, `source`, `library`, `chunks_indexed`, `status` (`indexed | skipped | replaced`)
- All I/O via `asyncio.to_thread()` — never blocks the MCP event loop

### `server.py`
- MCP entry point; registers all seven tools
- Loads embedder singleton at startup (before accepting requests)
- Selects transport from `MCP_TRANSPORT`:
  - `stdio` → subprocess mode for Claude Desktop local install
  - `sse` → HTTP/SSE mode for k3s hosted deployment
- **CRITICAL:** No `print()` anywhere in this file or anything it imports.
  All logging to stderr or `LOG_FILE`. One stray stdout byte silently breaks stdio transport.

---

## MCP Tool Contracts

Source of truth is `docs/mcp-tool-spec.md`. Do not rename or change parameter shapes
without updating that file and bumping the server version.

| Tool | Parameters | Returns |
|------|-----------|---------|
| `ingest_file` | `path: str`, `library: str = "default"`, `metadata: dict \| None` | `IngestResult` |
| `ingest_url` | `url: str`, `library: str = "default"`, `metadata: dict \| None` | `IngestResult` |
| `search` | `query: str`, `top_k: int = 5`, `library: str \| None = None`, `filter: dict \| None` | `list[SearchResult]` |
| `list_documents` | `library: str \| None = None`, `limit: int = 20`, `offset: int = 0` | `list[DocumentSummary]` |
| `list_libraries` | _(no parameters)_ | `list[LibrarySummary]` |
| `delete_document` | `doc_id: str` | `DeleteResult` |
| `get_document` | `doc_id: str` | `DocumentContent` |

**`library` parameter semantics:**
- `ingest_file` / `ingest_url`: if omitted, falls back to `DEFAULT_LIBRARY` from config (e.g. `"default"`). Free-form string — any name is valid, no pre-registration needed.
- `search` / `list_documents`: `library=None` means search/list across all libraries; a string scopes to that library only.
- `list_libraries`: returns distinct library names with document and chunk counts. Claude Desktop calls this first to discover available libraries before asking the user to choose one.
- `delete_document`: operates by `doc_id` which is globally unique — no `library` param needed.

**Typical Claude Desktop interaction flow:**
```
User:  "What libraries do I have?"
Claude: list_libraries() → [{name: "research", docs: 12}, {name: "personal", docs: 34}]

User:  "Index this PDF into my research library"
Claude: ingest_file(path="/path/to/paper.pdf", library="research")

User:  "Search my work library for quarterly reports"
Claude: search(query="quarterly reports", library="work")

User:  "Search everything for machine learning"
Claude: search(query="machine learning", library=None)
```

---

## Reuse Matrix

| Existing file | Action | What changes |
|---------------|--------|--------------|
| `converter.py` | **Adapt** | Add URL pass-through; add audio/image extensions; rename error class |
| `chunker.py` | **Adapt** | Swap `length_function` to tokenizer; units become tokens |
| `embedder.py` (`LocalEmbedder`) | **Adapt** | Change model to nomic; add `embed_documents`/`embed_query` split; drop `HuggingFaceEmbedder` |
| `resources.py` | **Drop** | Replace with embedder singleton in `server.py` startup only |
| `indexer.py` | **Drop** | Replaced entirely by `store.py` (LanceDB) |
| `data_ingestion.py` | **Drop** | 100% 3GPP/HuggingFace specific; no reusable code |

---

## Build Order

Each module is completed with tests before moving to the next.

```
1. config.py        — foundation; everything else imports this
2. converter.py     — no internal deps; easy to test in isolation
3. chunker.py       — depends on config only
4. embedder.py      — depends on config only; slow tests marked @slow
5. store.py         — depends on config + chunker schema
6. ingestor.py      — integrates converter + chunker + embedder + store
7. server.py        — wires everything together; MCP tool registration
```

---

## Testing Strategy

- Framework: pytest via `uv run pytest`
- Default run excludes `@pytest.mark.slow` (audio, OCR, embedding model load)
- All LanceDB tests use `tmp_path` fixture — never the user's real database
- All URL tests mock MarkItDown's HTTP calls — no real network in test suite
- One sample fixture file per supported format in `examples/sample_docs/`
- Coverage target: 80% lines/branches across `src/mcpvectordb/`

| Marker | Used for |
|--------|---------|
| `slow` | Embedding model load, audio transcription, image OCR |
| `integration` | Tests that write to real (tmp) LanceDB |
| `unit` | Pure functions, no I/O |

---

## Deployment Modes

| Mode | Transport | LanceDB URI | Claude Desktop config |
|------|-----------|-------------|----------------------|
| Local dev | stdio | `~/.mcpvectordb/lancedb` | `command: uv run mcpvectordb` |

---

## Out of Scope (v1)

- Watch folder / filesystem auto-indexing (deferred to v2 as standalone CLI script)
- Hybrid search (vector + full-text combined scoring)
- Reranking (cross-encoder second pass)
- Multi-user / multi-index support
- Web scraping beyond simple article pages (JS-rendered content)
- API-based embeddings fallback
