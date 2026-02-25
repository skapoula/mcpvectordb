# MCP Tool Specification — mcpvectordb

> **Source of truth.** Do not rename tools or change parameter shapes without updating
> this file and bumping the server version. Breaking changes require a new tool name.

---

## Server Info

| Field | Value |
|-------|-------|
| Name | `mcpvectordb` |
| Version | `0.3.0` |
| Transport | `stdio` (default) or `sse` (HTTP, k3s) |
| Embedding model | `nomic-embed-text-v1.5` (768d) |
| Search | Hybrid BM25 + vector (reciprocal rank fusion) |

---

## Tools

### `ingest_file`

Convert a local file and index it in the vector store.

**Input schema:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | `string` | Yes | — | Absolute or relative path to the file |
| `library` | `string` | No | `"default"` | Library (collection) to index into |
| `metadata` | `object \| null` | No | `null` | Arbitrary key-value metadata |

**Output schema (success):**

```json
{
  "status": "indexed | replaced | skipped",
  "doc_id": "<uuid>",
  "source": "/abs/path/to/file.pdf",
  "library": "default",
  "chunk_count": 12
}
```

**Output schema (error):**

```json
{ "status": "error", "error": "Human-readable error message" }
```

**Dedup behaviour:** If the same `(path, library)` pair has been ingested before:
- Same content hash → `status: "skipped"`, nothing written
- Different content hash → old document deleted, re-indexed → `status: "replaced"`

---

### `ingest_content`

Index pre-extracted text content directly, without reading from the server filesystem.

Use this when Claude Desktop has already read a file (e.g. a user upload) and the
server cannot access that path on disk. Read or extract the text yourself and pass it
as the `content` parameter.

**Input schema:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `content` | `string` | Yes | — | Full text or Markdown to index |
| `source` | `string` | Yes | — | Label for the origin (filename, URL, etc.) — used for dedup and display |
| `library` | `string` | No | `"default"` | Library to index into |
| `metadata` | `object \| null` | No | `null` | Arbitrary key-value metadata |

**Output schema:** Same as `ingest_file`.

**Dedup behaviour:** Same as `ingest_file` but keyed on `(source, library)`.

---

### `ingest_url`

Fetch an HTTP/HTTPS URL, convert its content, and index it.

**Input schema:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | `string` | Yes | — | HTTP or HTTPS URL to fetch |
| `library` | `string` | No | `"default"` | Library to index into |
| `metadata` | `object \| null` | No | `null` | Arbitrary key-value metadata |

**Output schema:** Same as `ingest_file`.

**Dedup behaviour:** Same as `ingest_file` but keyed on `(url, library)`.

---

### `search`

Semantic search over indexed document chunks.

**Input schema:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | `string` | Yes | — | Natural language search query |
| `top_k` | `integer` | No | `5` | Max results to return (1–100) |
| `library` | `string \| null` | No | `null` | Restrict to library; `null` = all libraries |
| `filter` | `object \| null` | No | `null` | Field equality filters (see below) |

**`filter` format:**

An object mapping any `ChunkRecord` field name to a value. All conditions are AND-ed.
String and integer values are supported. Invalid key names raise an error.

```json
{ "file_type": "pdf" }
{ "file_type": "pdf", "page": 3 }
{ "last_modified": "2025-01-01T00:00:00+00:00" }
```

Useful filterable fields: `file_type`, `page`, `last_modified`, `source`, `title`.
The `library` parameter is the preferred way to filter by library; it can also appear in `filter`.

**Output schema (success):**

```json
{
  "results": [
    {
      "doc_id": "<uuid>",
      "source": "/path/or/url",
      "title": "Document Title",
      "library": "default",
      "file_type": "pdf",
      "last_modified": "2025-06-01T09:00:00+00:00",
      "page": 0,
      "content": "The matching chunk text...",
      "chunk_index": 3,
      "metadata": {}
    }
  ]
}
```

Results are sorted by hybrid relevance (BM25 + vector) descending.
`page` is `0` when the page number is unknown or not applicable.

---

### `list_documents`

List indexed documents with metadata.

**Input schema:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `library` | `string \| null` | No | `null` | Filter by library; `null` = all |
| `limit` | `integer` | No | `20` | Max documents to return (1–1000) |
| `offset` | `integer` | No | `0` | Pagination offset |

**Output schema:**

```json
{
  "documents": [
    {
      "doc_id": "<uuid>",
      "source": "/path/or/url",
      "title": "Document Title",
      "library": "default",
      "content_hash": "<sha256>",
      "created_at": "2025-01-01T00:00:00+00:00",
      "metadata": {},
      "chunk_count": 12
    }
  ],
  "count": 1
}
```

---

### `list_libraries`

List all libraries with document and chunk counts.

**Input schema:** No parameters.

**Output schema:**

```json
{
  "libraries": [
    {
      "library": "default",
      "document_count": 5,
      "chunk_count": 47
    }
  ]
}
```

---

### `delete_document`

Remove a document and all its chunks from the index.

**Input schema:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `doc_id` | `string` | Yes | The document UUID to delete |

**Output schema (success):**

```json
{ "status": "deleted", "doc_id": "<uuid>", "deleted_chunks": 12 }
```

---

### `get_document`

Return the full Markdown text of an indexed document.

**Input schema:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `doc_id` | `string` | Yes | The document UUID to retrieve |

**Output schema (success):**

```json
{
  "doc_id": "<uuid>",
  "source": "/path/or/url",
  "title": "Document Title",
  "library": "default",
  "content": "Full reconstructed Markdown text...",
  "chunk_count": 12,
  "metadata": {}
}
```

---

### `server_info`

Return server diagnostics. Use this to verify the installation and check whether
the server can read a specific file path before attempting ingestion.

**Input schema:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `check_path` | `string \| null` | No | `null` | File path to test for readability |

**Output schema:**

```json
{
  "platform": "win32",
  "python_version": "3.13.1",
  "cwd": "C:\\Users\\you\\mcpvectordb",
  "lancedb_uri": "C:\\Users\\you\\AppData\\Local\\mcpvectordb\\lancedb",
  "fastembed_cache_path": "C:\\Users\\you\\AppData\\Local\\mcpvectordb\\models",
  "transport": "stdio",
  "note": "In stdio mode the server runs on the same machine as Claude Desktop...",
  "path_check": {
    "path": "C:\\Users\\you\\Documents\\report.pdf",
    "readable": true,
    "size_bytes": 204800
  }
}
```

`path_check` is only present when `check_path` is supplied.
If the file is not readable, `path_check.readable` is `false` and `path_check.error` describes why.

---

## Error Response (all tools)

Any tool may return an error response:

```json
{ "status": "error", "error": "Human-readable description of what went wrong" }
```

Tools never let exceptions propagate to the MCP framework — all errors are returned
as structured error responses.

---

## HTTP Endpoints

### `ingest_folder`

Ingest all supported documents in a folder into the vector index.

Scans the folder for files with supported extensions and runs them through the full
pipeline (convert → chunk → embed → store) in parallel. Files that fail are reported
in `errors` without stopping the rest of the batch.

**Input schema:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `folder` | `string` | Yes | — | Absolute or relative path to the folder to ingest |
| `library` | `string` | No | `"default"` | Library (collection) to index into |
| `metadata` | `object \| null` | No | `null` | Key-value metadata attached to every document |
| `recursive` | `boolean` | No | `true` | Scan subdirectories recursively |
| `max_concurrency` | `integer` | No | `4` | Max files processed simultaneously (≥ 1) |

**Output schema (success):**

```json
{
  "folder": "/abs/path/to/folder",
  "library": "default",
  "total_files": 12,
  "indexed": 10,
  "replaced": 1,
  "skipped": 1,
  "failed": 0,
  "results": [
    {
      "status": "indexed",
      "doc_id": "<uuid>",
      "source": "/abs/path/to/folder/doc.pdf",
      "library": "default",
      "chunk_count": 8
    }
  ],
  "errors": []
}
```

`errors` contains one entry per failed file: `{"file": "<path>", "error": "<message>"}`.

**Output schema (error):**

```json
{ "status": "error", "error": "Human-readable error message" }
```

**Guard conditions:**
- `folder` empty → error
- `max_concurrency < 1` → error
- Folder path does not exist or is a file → `IngestionError` → error response

---

### POST /upload

Upload a file directly from any HTTP client. The server receives the raw bytes and
runs the full parsing pipeline (markitdown → chunk → embed → store). Use this when
the file is not accessible on the server filesystem — e.g. a file on a Windows host
connecting to a containerised server via an HTTPS tunnel.

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | binary | Yes | The file to ingest |
| `library` | string | No | Library name (default: `"default"`) |
| `metadata` | string | No | JSON object string, e.g. `{"author":"Alice"}` |

**Response:** Same JSON schema as `ingest_file`.

**Error responses:**

| Status | Meaning |
|--------|---------|
| 400 | Missing `file` field, form parse error, or invalid `metadata` JSON |
| 422 | File extension not supported by markitdown |
| 500 | Ingestion pipeline error |

**curl:**
```bash
curl -X POST https://<host>/upload \
  -F "file=@report.pdf" \
  -F "library=research"
```

**PowerShell:**
```powershell
Invoke-RestMethod -Uri "https://<host>/upload" -Method Post `
  -Form @{ file = Get-Item "C:\docs\report.pdf"; library = "research" }
```

---

## Standalone CLI — `mcpvectordb-ingest`

Bulk-ingest a folder of documents without starting the MCP server. Writes to the same
LanceDB path as the server (controlled by `LANCEDB_URI`), so the store is ready when
Claude Desktop connects the next morning.

**Usage:**

```bash
mcpvectordb-ingest <folder> [options]
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--library <name>` | `default` | Library to index into |
| `--no-recursive` | *(off)* | Do not scan subdirectories |
| `--max-concurrency <n>` | `4` | Max files processed simultaneously |

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0 | All files ingested successfully (or none found) |
| 1 | One or more files failed, or a fatal error occurred |
| 2 | Invalid arguments (argparse error) |

**Example — overnight indexing workflow:**

```bash
# Index a research folder overnight
mcpvectordb-ingest ~/Documents/research --library research --max-concurrency 8

# Next morning: start the MCP server — Claude Desktop queries the pre-built store
uv run mcpvectordb
```

Errors are printed to `stderr`; the summary is printed to `stdout`.
