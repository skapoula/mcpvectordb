# LanceDB Optimization Best Practices
> **Audience:** Claude Code — Planning Mode  
> **Purpose:** Use this document when analyzing, designing, or optimizing any application that uses LanceDB as a vector store. Apply these practices during architecture review, code generation, and retrieval pipeline planning.

---

## 1. Chunking Strategy

**Rule:** Never ingest whole files as single documents.

Use **Recursive Character Splitting** — split by paragraphs first, then sentences, then words. This preserves logical units and prevents cutting sentences mid-thought, which degrades retrieval quality.

**Target parameters:**
- Chunk size: 512–1000 tokens
- Overlap: 10–20% of chunk size (e.g., 100 tokens overlap for a 512-token chunk)

**Contextual Retrieval enhancement:** Prepend a short document-level summary to each chunk before embedding. This ensures a chunk from page 50 still carries context about the parent document (e.g., "This chunk is from the Project Alpha deployment manual"). This technique is called *situated search* and significantly improves recall for long documents.

**When planning ingestion pipelines, flag any code that:**
- Passes raw file content directly to an embedding model
- Uses fixed-character splitting without sentence awareness
- Sets chunk size below 256 or above 1500 tokens without justification

---

## 2. Metadata — Store It Alongside Every Vector

**Rule:** Every vector in LanceDB must have structured metadata attached.

Minimum required fields per record:

| Field | Example | Purpose |
|---|---|---|
| `source` | `manuals/deployment.pdf` | Source citation |
| `page` | `4` | Page-level citation |
| `last_modified` | `2024-11-01` | Staleness filtering |
| `file_type` | `pdf` | Type-based filtering |
| `author` | `engineering-team` | Ownership filtering |

This enables Claude to produce citations like *"According to page 4 of deployment.pdf..."* and allows pre-filtering before vector search, which is both faster and more accurate than relying on vectors alone.

**When planning retrieval logic, flag any query that:**
- Does not leverage metadata filters when the user query contains explicit constraints (year, document type, author, etc.)
- Makes the vector search do work that a scalar index can handle

---

## 3. Hybrid Search — Vector + Full-Text (BM25)

**Rule:** Always implement hybrid search. Vector-only retrieval fails on exact-match queries (model numbers, version strings, proper nouns).

Combine:
- **Semantic vector search** — for conceptual similarity
- **BM25 full-text search** — for exact term matching

LanceDB supports both natively. The result fusion ensures that a query like *"error code E-4021"* will find the exact string even if the vector embedding for that phrase is imprecise.

**When planning search pipelines, ensure:**
- Both search modes are invoked and results are fused (reciprocal rank fusion or weighted scoring)
- Neither mode is used in isolation for production retrieval

---

## 4. LanceDB Query Parameters — Tune for Recall

### `refine_factor`
After ANN search returns approximate candidates, `refine_factor` re-fetches exact vectors for a subset of results and recomputes precise distances. This improves recall with minimal latency cost.

```python
table.search(query_vector).refine_factor(10).limit(5).to_list()
```

### `nprobes` (IVF-PQ indexes)
Controls how many index clusters are scanned during search. Higher = better recall, slightly higher latency.

**Target:** Cover 5–10% of your dataset. For a 10,000-row table with 100 clusters, set `nprobes=5` to `nprobes=10`.

```python
table.search(query_vector).nprobes(10).limit(5).to_list()
```

**When reviewing query code, flag:**
- Default `nprobes` on large tables (>50k rows) without justification
- Missing `refine_factor` on production retrieval paths

---

## 5. Metadata Filtering with Scalar Indexes

**Rule:** Create scalar indexes on any column used repeatedly in filters.

```python
table.create_scalar_index("file_type")
table.create_scalar_index("author")
table.create_scalar_index("year")
```

Pre-filtering by scalar index before vector search reduces the search space and eliminates the need to rank irrelevant documents. A filter like `year == 2024` is 100% accurate; asking a vector to rank documents for "2024" is not.

---

## 6. Ingestion Performance

**Rule:** Always batch insert. Never insert records one-by-one.

```python
# Correct — batch insert
table.add([{"text": chunk, "vector": vec, "source": path} for chunk, vec in results])

# Incorrect — row-by-row (creates excessive small fragments on disk)
for chunk, vec in results:
    table.add({"text": chunk, "vector": vec, "source": path})
```

For parallel file parsing, use `n_jobs` in document loaders (e.g., LangChain's `DirectoryLoader`) to utilize all available CPU cores during the parse phase.

```python
from langchain.document_loaders import DirectoryLoader
loader = DirectoryLoader("./docs", glob="**/*.pdf", n_jobs=-1)  # -1 = all cores
```

---

## 7. Storage Format

**Rule:** Use LanceDB's native `.lance` format. Do not convert to Parquet or other formats for production retrieval workloads.

The `.lance` format is optimized for columnar random access, which is the dominant access pattern during vector search. Conversion eliminates these optimizations.

---

## 8. Embedding Model — CPU-Optimized Default

**Recommended model:** `nomic-ai/nomic-embed-text-v1.5`

**Why:**
- Supports **Matryoshka Embeddings** — vectors can be truncated to smaller dimensions without retraining, reducing index size and query latency
- Strong retrieval quality on technical documents
- Efficient on CPU (no GPU required)
- Native integration via LanceDB's `EmbeddingFunctionRegistry`

```python
from lancedb.embeddings import get_registry

registry = get_registry()
model = registry.get("sentence-transformers").create(name="nomic-ai/nomic-embed-text-v1.5")
```

**Critical rule:** The embedding model used at **ingestion time must be identical** to the model used at **query time**. A mismatch produces semantically meaningless similarity scores. This should be enforced via a config constant, never hardcoded in two separate places.

```python
# config.py — single source of truth
EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"
```

---

## Planning Checklist

When Claude Code reviews or generates a LanceDB-backed application, verify:

- [ ] Chunking uses recursive splitting with 512–1000 token target and 10–20% overlap
- [ ] Every record stores `source`, `page`, and `last_modified` metadata
- [ ] Hybrid search (vector + BM25) is implemented
- [ ] `refine_factor` is set on retrieval queries
- [ ] `nprobes` is tuned for tables with IVF-PQ indexes
- [ ] Scalar indexes exist on all frequently filtered columns
- [ ] Ingestion uses batch inserts, not row-by-row
- [ ] Storage remains in `.lance` format
- [ ] Embedding model is defined in one config constant used for both ingestion and retrieval
- [ ] `n_jobs=-1` is used in document loaders for CPU parallelism
