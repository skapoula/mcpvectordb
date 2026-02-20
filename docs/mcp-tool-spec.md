# MCP Tool Specification — mcpvectordb

> **Source of truth.** Do not rename tools or change parameter shapes without updating
> this file and bumping the server version. Breaking changes require a new tool name.

---

## Server Info

| Field | Value |
|-------|-------|
| Name | `mcpvectordb` |
| Version | `0.2.0` |
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

## Error Response (all tools)

Any tool may return an error response:

```json
{ "status": "error", "error": "Human-readable description of what went wrong" }
```

Tools never let exceptions propagate to the MCP framework — all errors are returned
as structured error responses.
