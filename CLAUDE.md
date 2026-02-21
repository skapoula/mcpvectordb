# CLAUDE.md — mcpvectordb

> **Scope:** PROJECT-LEVEL — inherits org-wide policy from `/workspace/CLAUDE.md`.
> Rules here extend or override global where they conflict.
> Personal overrides go in `CLAUDE.local.md` (auto-gitignored).

<!-- Global context loaded automatically via directory traversal — no import needed. -->

---

## Project Overview

`mcpvectordb` is an MCP (Model Context Protocol) server that gives Claude Desktop
semantic search over a personal document library. Documents are ingested from local
files or URLs, converted to Markdown via **MarkItDown**, chunked, embedded, and stored
in **LanceDB**. Claude Desktop queries the server over stdio (local) or SSE over HTTP
(hosted on k3s), both supported via a single config flag.

```
Local files / URLs
       │
       ▼
MarkItDown[all] ──► Markdown text
       │
       ▼
Chunker + Embedder (sentence-transformers)
       │
       ▼
LanceDB  ◄──────────────────── configurable URI
  (local dir │ k3s PVC │ remote)
       │
       ▼
MCP Server
  ├── stdio transport   ◄──► Claude Desktop (host OS subprocess)
  └── SSE/HTTP transport◄──► Claude Desktop (k3s hosted, URL-based)
```

**Supported input formats (via `markitdown[all]`):**
PDF · Word (.docx) · PowerPoint (.pptx) · Excel (.xlsx) · HTML / web pages ·
Images (OCR) · Audio (transcription) · and any other format MarkItDown supports.

Install with:
```bash
uv add 'markitdown[all]'
# or for an existing venv:
pip install 'markitdown[all]'
```

**Key libraries:** `markitdown[all]` · `lancedb` · `mcp` · `sentence-transformers` ·
`httpx` · `pydantic` · `pydantic-settings` · `python-dotenv`

---

## Architecture

```
mcpvectordb/
├── src/
│   └── mcpvectordb/
│       ├── __init__.py
│       ├── server.py          # MCP entry point; registers tools; selects transport (inline)
│       ├── exceptions.py      # Domain exception classes
│       ├── ingestor.py        # Orchestrates file/URL → Markdown → LanceDB pipeline
│       ├── converter.py       # markitdown[all] wrapper; dispatch by extension/MIME
│       ├── chunker.py         # Recursive token-aware text splitting
│       ├── embedder.py        # sentence-transformers wrapper; batched encoding
│       ├── store.py           # LanceDB read/write; schema; migration helpers
│       └── config.py          # pydantic-settings; all settings from .env
├── tests/
│   ├── conftest.py            # Fixtures: tmp LanceDB dir, sample docs per format
│   ├── test_converter.py      # One test per supported file type
│   ├── test_chunker.py
│   ├── test_embedder.py
│   ├── test_store.py
│   ├── test_ingestor.py       # Ingestor pipeline, dedup scenarios
│   └── test_server.py         # MCP tool contract tests
├── docs/
│   └── mcp-tool-spec.md       # Tool names, input schemas, return schemas — source of truth
├── examples/
│   └── sample_docs/           # Small fixture files, one per supported format
├── deploy/
│   └── k3s/
│       ├── deployment.yaml    # k3s Deployment for SSE transport
│       ├── service.yaml       # ClusterIP / NodePort service
│       └── pvc.yaml           # PersistentVolumeClaim for LanceDB data
├── pyproject.toml             # Always this exact name — Python packaging standard
├── .env.example               # Committed template; real .env is gitignored
├── CLAUDE.md                  ← THIS FILE
└── CLAUDE.local.md            ← personal overrides (gitignored)
```

> **Note on `pyproject.toml` naming:** This file is always named `pyproject.toml` —
> it cannot be renamed. Each project in the workspace has its own in its own directory.
> `uv` and all Python tooling scope everything by the directory you run commands from,
> so `/workspace/mcpvectordb/pyproject.toml` and `/workspace/specagent/pyproject.toml`
> are completely independent with no collision.

---

## Common Commands

```bash
# Install all dependencies including markitdown[all]
uv sync
# or: pip install 'markitdown[all]' for the full format support

# Run server — stdio transport (Claude Desktop subprocess mode)
uv run mcpvectordb

# Run server — SSE/HTTP transport (k3s hosted mode)
MCP_TRANSPORT=sse MCP_HOST=0.0.0.0 MCP_PORT=8000 uv run mcpvectordb

# Run tests (excludes slow audio/OCR tests by default)
uv run pytest

# Run a single test file
uv run pytest tests/test_converter.py -v

# Run by marker
uv run pytest -m "not slow" -v        # skip heavy transcription/OCR tests
uv run pytest -m integration -v       # tests that write to real tmp LanceDB
uv run pytest -m unit -v              # pure function tests, no I/O

# Lint + format (ruff handles both)
uv run ruff check . && uv run ruff format .

# Type-check
uv run mypy src/

# Security scan
uv run bandit -r src/

# Build package
uv build
```

---

## Deployment — Local (Claude Desktop on host OS, stdio)

Claude Desktop spawns the server as a subprocess. Communication is over stdin/stdout.
LanceDB writes to a local directory on the host filesystem.

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):
```json
{
  "mcpServers": {
    "mcpvectordb": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcpvectordb", "mcpvectordb"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "LANCEDB_URI": "/Users/<you>/.mcpvectordb/lancedb"
      }
    }
  }
}
```


---

## MCP Tools Exposed to Claude Desktop

Source of truth for tool contracts is `docs/mcp-tool-spec.md`.
Do not rename tools or change parameter shapes without updating that file and bumping
the server version. Breaking changes require a new tool name, not a modified one.

| Tool | Description | Key parameters |
|------|-------------|----------------|
| `ingest_file` | Convert a local file and index it | `path: str`, `library: str = "default"`, `metadata: dict \| None` |
| `ingest_url` | Fetch a URL, convert, and index it | `url: str`, `library: str = "default"`, `metadata: dict \| None` |
| `ingest_content` | Index pre-extracted text directly (e.g. from a user upload) | `content: str`, `source: str`, `library: str = "default"`, `metadata: dict \| None` |
| `search` | Semantic search over the index | `query: str`, `top_k: int = 5`, `library: str \| None = None`, `filter: dict \| None` |
| `list_documents` | List indexed documents with metadata | `library: str \| None = None`, `limit: int = 20`, `offset: int = 0` |
| `list_libraries` | List all libraries with document counts | _(no parameters)_ |
| `delete_document` | Remove a document and all its chunks | `doc_id: str` |
| `get_document` | Return full Markdown text of a document | `doc_id: str` |

---

## LanceDB Schema

Each chunk is one row. Schema changes require a migration — do not alter casually.

```python
class ChunkRecord(BaseModel):
    id: str               # uuid4 — chunk-level unique ID
    doc_id: str           # uuid4 — groups all chunks from one source document
    library: str          # collection name — free-form, defaults to DEFAULT_LIBRARY
    source: str           # original file path or URL
    content_hash: str     # SHA256 of raw source bytes, for deduplication
    title: str            # document title (inferred or from metadata)
    content: str          # the Markdown chunk text
    embedding: list[float]  # nomic-embed-text-v1.5 dense vector (768d)
    chunk_index: int      # position of this chunk within its document
    created_at: str       # ISO 8601 timestamp
    metadata: str         # JSON-serialised dict of user-supplied key-value pairs
```

---

## Configuration (`.env`)

All runtime settings go through `config.py` (pydantic-settings). Never hardcode values.

```bash
# .env.example — commit this file; never commit .env

# ── Transport ──────────────────────────────────────────────────────────────────
MCP_TRANSPORT=stdio            # stdio | sse
MCP_HOST=127.0.0.1             # SSE only — bind address
MCP_PORT=8000                  # SSE only — listen port

# ── LanceDB ────────────────────────────────────────────────────────────────────
# Set this to match your deployment mode:
#   Local dev:      ~/.mcpvectordb/lancedb
#   k3s PVC:        /data/lancedb
#   Remote/S3:      s3://bucket/path  (LanceDB supports s3:// URIs)
LANCEDB_URI=~/.mcpvectordb/lancedb
LANCEDB_TABLE_NAME=documents
DEFAULT_LIBRARY=default            # fallback library name when not specified in tool call

# ── Embedding ──────────────────────────────────────────────────────────────────
EMBEDDING_MODEL=nomic-embed-text-v1.5  # WARNING: changing this requires full re-index
EMBEDDING_BATCH_SIZE=32

# ── Chunking ───────────────────────────────────────────────────────────────────
CHUNK_SIZE_TOKENS=512
CHUNK_OVERLAP_TOKENS=64
CHUNK_MIN_TOKENS=50

# ── URL fetching ───────────────────────────────────────────────────────────────
HTTP_TIMEOUT_SECONDS=10
HTTP_USER_AGENT=mcpvectordb/1.0

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_LEVEL=INFO                     # DEBUG | INFO | WARNING | ERROR
# In stdio mode all logs MUST go to a file or stderr — never stdout
LOG_FILE=~/.mcpvectordb/server.log # optional; unset = stderr only
```

---

## Converter Dispatch

`converter.py` delegates to `markitdown[all]` for all format support. Dispatch order:

1. If input is an `http(s)://` URL → fetch with `httpx`, then convert as HTML
2. Else dispatch by file extension (case-insensitive)
3. If extension is unrecognised → raise `UnsupportedFormatError(ext)`

Never silently ignore an unsupported format. A loud failure is always preferable to
empty or wrong content being indexed.

Audio transcription and image OCR are slow — tag those tests `@pytest.mark.slow`.

---

## Testing Conventions

- `uv run pytest` — default run, excludes `slow` marker
- Markers (must be declared in `pyproject.toml` under `[tool.pytest.ini_options]`):
  - `slow` — audio transcription, image OCR, large file tests
  - `integration` — writes to real (tmp) LanceDB on disk
  - `unit` — pure functions, no I/O, no filesystem
- Always use `tmp_path` fixture for LanceDB in tests — never the user's real database
- Mock `httpx` in all URL tests — no real network calls in the test suite
- One fixture file per supported format in `examples/sample_docs/` (keep them tiny)
- Test `UnsupportedFormatError` is raised for unknown extensions

---

## Code Style

Beyond the global rules in `/workspace/.claude/rules/code-style.md`:

- Python 3.11+. Type hints on all public function signatures (params + return type).
- Ruff for linting and formatting (line length 88, Black-compatible).
- Pydantic models for all data crossing module boundaries.
- `pathlib.Path` everywhere — never `os.path` or raw string paths.
- All public functions need at minimum a one-line docstring.
- IMPORTANT: Do not add or remove type annotations without an explicit instruction.

---

## Terminology

| Term | Meaning |
|------|---------|
| **document** | A single source file or URL — the top-level ingestion unit |
| **chunk** | A text fragment stored as one LanceDB row with its own embedding |
| **doc_id** | UUID grouping all chunks from one source document |
| **embedding** | Dense float vector produced by the embedding model for a chunk |
| **MCP tool** | A named, schema-typed function the server exposes to Claude Desktop |
| **ingest** | Full pipeline: fetch/read → convert → chunk → embed → store |
| **transport** | How Claude Desktop connects: `stdio` (subprocess) or `sse` (HTTP) |
| **MarkItDown** | Microsoft's open-source file-to-Markdown library (`markitdown[all]`) |
| **LanceDB** | Embedded vector DB; no separate server process; supports local + S3 URIs |

---

## Do Not

Extends global Do Not. Project-specific hard rules:

| Rule | Reason |
|------|---------|
| **No `print()` to stdout anywhere in the server or its imports** | In stdio mode, any stray stdout byte corrupts the MCP framing; Claude Desktop fails silently |
| **No schema changes to `ChunkRecord`** without a migration script and human approval | Breaks all existing indexed data |
| **No changing `EMBEDDING_MODEL`** without a full re-index plan | Vectors from different models are incompatible; search silently returns garbage |
| **No real network calls in tests** — mock `httpx` | Tests must pass offline |
| **No writing to the user's real LanceDB in tests** — always use `tmp_path` | Prevents test runs corrupting the live index |
| **No silent swallowing of unsupported formats** — raise `UnsupportedFormatError` | Silent failures produce empty or missing index entries |
| **No hardcoded paths** — all paths through `config.py` and `.env` | Required for multi-mode deployment (local / k3s / remote) |

---

## Project Imports

@.claude/rules/code-style.md
@.claude/rules/testing.md
@.claude/rules/lancedb-best-practices.md
@.claude/rues/repo-docs-best-practices.md
