# API Reference

mcpvectordb exposes MCP tools — not an HTTP REST API. Tools are invoked by Claude
Desktop via the MCP protocol (stdio or SSE transport). Parameters are JSON-typed;
all responses are JSON objects.

**Authentication:** None. The MCP protocol handles transport security.

**Error response (all tools):**

```json
{ "status": "error", "error": "Human-readable description of what went wrong" }
```

Tools never let exceptions propagate — all failures return a structured error response.

---

## Tools

### `ingest_file`

Convert a local file and index it in the vector store.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | Yes | — | Absolute or relative path to the file |
| `library` | string | No | `"default"` | Library (collection) to index into |
| `metadata` | object \| null | No | `null` | Arbitrary key-value metadata to attach |

**Supported file types:** `.pdf`, `.docx`, `.doc`, `.pptx`, `.ppt`, `.xlsx`, `.xls`,
`.html`, `.htm`, `.txt`, `.md`, `.csv`, `.json`, `.xml`, `.jpg`, `.jpeg`, `.png`,
`.gif`, `.bmp`, `.webp`, `.mp3`, `.wav`, `.ogg`, `.m4a`, `.zip`

**Success response:**

```json
{
  "status": "indexed",
  "doc_id": "3f2a1b4c-...",
  "source": "/Users/alex/papers/attention.pdf",
  "library": "research",
  "chunk_count": 18
}
```

`status` is one of `"indexed"`, `"replaced"` (re-indexed after content change),
or `"skipped"` (identical content already in the index).

---

### `ingest_url`

Fetch an HTTP/HTTPS URL, convert its content, and index it.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `url` | string | Yes | — | HTTP or HTTPS URL to fetch |
| `library` | string | No | `"default"` | Library to index into |
| `metadata` | object \| null | No | `null` | Arbitrary key-value metadata to attach |

**Success response:** Same shape as `ingest_file`.

---

### `search`

Hybrid semantic search (BM25 + vector, reciprocal rank fusion) over indexed chunks.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | Yes | — | Natural language search query |
| `top_k` | integer | No | `5` | Max results to return (1–100) |
| `library` | string \| null | No | `null` | Restrict to this library; `null` = all libraries |
| `filter` | object \| null | No | `null` | Field equality filters (AND-ed) |

**`filter` examples:**

```json
{ "file_type": "pdf" }
{ "file_type": "pdf", "page": 3 }
{ "last_modified": "2025-01-01T00:00:00+00:00" }
```

Filterable fields: `file_type`, `page`, `last_modified`, `source`, `title`.

**Success response:**

```json
{
  "results": [
    {
      "doc_id": "3f2a1b4c-...",
      "source": "/Users/alex/papers/attention.pdf",
      "title": "Attention Is All You Need",
      "library": "research",
      "file_type": "pdf",
      "last_modified": "2025-06-01T09:00:00+00:00",
      "page": 4,
      "content": "The encoder maps an input sequence of symbol representations...",
      "chunk_index": 7,
      "metadata": {}
    }
  ]
}
```

Results are sorted by hybrid relevance descending. `page` is `0` when not applicable.

---

### `list_documents`

List indexed documents with metadata.

**Parameters:**

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `library` | string \| null | No | `null` | Filter by library; `null` = all libraries |
| `limit` | integer | No | `20` | Max documents to return (1–1000) |
| `offset` | integer | No | `0` | Pagination offset |

**Success response:**

```json
{
  "documents": [
    {
      "doc_id": "3f2a1b4c-...",
      "source": "/Users/alex/papers/attention.pdf",
      "title": "Attention Is All You Need",
      "library": "research",
      "content_hash": "e3b0c44298fc...",
      "created_at": "2025-06-01T09:00:00+00:00",
      "metadata": {},
      "chunk_count": 18
    }
  ],
  "count": 1
}
```

---

### `list_libraries`

List all libraries with document and chunk counts. No parameters.

**Success response:**

```json
{
  "libraries": [
    {
      "library": "research",
      "document_count": 3,
      "chunk_count": 54
    }
  ]
}
```

---

### `delete_document`

Remove a document and all its chunks from the index.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `doc_id` | string | Yes | UUID of the document to delete |

**Success response:**

```json
{ "status": "deleted", "doc_id": "3f2a1b4c-...", "deleted_chunks": 18 }
```

---

### `get_document`

Return the full Markdown text of an indexed document (chunks concatenated in order).

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `doc_id` | string | Yes | UUID of the document to retrieve |

**Success response:**

```json
{
  "doc_id": "3f2a1b4c-...",
  "source": "/Users/alex/papers/attention.pdf",
  "title": "Attention Is All You Need",
  "library": "research",
  "content": "# Attention Is All You Need\n\nThe dominant sequence...",
  "chunk_count": 18,
  "metadata": {}
}
```
