"""MCP server entry point — registers tools and selects transport."""

import json
import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mcpvectordb.config import settings
from mcpvectordb.embedder import get_embedder
from mcpvectordb.exceptions import IngestionError, StoreError, UnsupportedFormatError
from mcpvectordb.ingestor import ingest
from mcpvectordb.store import Store

# ── Logging setup ──────────────────────────────────────────────────────────────
# In stdio mode every byte on stdout corrupts MCP framing — log to stderr only.
_log_handlers: list[logging.Handler] = []
if settings.log_file:
    _log_handlers.append(logging.FileHandler(Path(settings.log_file).expanduser()))
_log_handlers.append(logging.StreamHandler(sys.stderr))

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    handlers=_log_handlers,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP("mcpvectordb")
_store = Store()


# ── Tool: ingest_file ──────────────────────────────────────────────────────────
@mcp.tool()
async def ingest_file(
    path: str,
    library: str = "default",
    metadata: dict | None = None,
) -> dict:
    """Ingest a local file into the vector index.

    Converts the file to Markdown, chunks it, embeds each chunk, and stores
    everything in LanceDB. Deduplicates by (path, library) and content hash.

    Args:
        path: Absolute or relative path to the file to ingest.
        library: Library (collection) name. Defaults to 'default'.
        metadata: Optional key-value metadata to attach to the document.

    Returns:
        Dict with status, doc_id, source, library, chunk_count.
    """
    try:
        result = await ingest(
            source=Path(path).resolve(),
            library=library,
            metadata=metadata,
            store=_store,
        )
        return result.model_dump()
    except UnsupportedFormatError as e:
        return {"error": f"Unsupported format: {e}", "status": "error"}
    except IngestionError as e:
        return {"error": f"Ingestion failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in ingest_file")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Tool: ingest_url ──────────────────────────────────────────────────────────
@mcp.tool()
async def ingest_url(
    url: str,
    library: str = "default",
    metadata: dict | None = None,
) -> dict:
    """Fetch a URL and ingest its content into the vector index.

    Downloads the page, converts HTML to Markdown, chunks, embeds, and stores.
    Deduplicates by (url, library) and content hash.

    Args:
        url: HTTP or HTTPS URL to fetch and ingest.
        library: Library (collection) name. Defaults to 'default'.
        metadata: Optional key-value metadata to attach to the document.

    Returns:
        Dict with status, doc_id, source, library, chunk_count.
    """
    if not url.startswith(("http://", "https://")):
        return {"error": "URL must start with http:// or https://", "status": "error"}
    try:
        result = await ingest(
            source=url,
            library=library,
            metadata=metadata,
            store=_store,
        )
        return result.model_dump()
    except IngestionError as e:
        return {"error": f"Ingestion failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in ingest_url")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Tool: search ──────────────────────────────────────────────────────────────
@mcp.tool()
async def search(
    query: str,
    top_k: int = 5,
    library: str | None = None,
    filter: dict | None = None,  # noqa: A002
) -> dict:
    """Hybrid search (BM25 + vector) over the indexed document library.

    Embeds the query for semantic search and uses the raw text for BM25 full-text
    search, combining both via reciprocal rank fusion for improved retrieval.

    Args:
        query: Natural language search query.
        top_k: Maximum number of results to return (default 5).
        library: Restrict search to this library. Searches all if None.
        filter: Reserved for future metadata filtering (unused in v1).

    Returns:
        Dict with 'results' list of matching chunks.
    """
    if not query.strip():
        return {"error": "query must not be empty", "status": "error"}
    if top_k < 1 or top_k > 100:
        return {"error": "top_k must be between 1 and 100", "status": "error"}
    try:
        import asyncio

        embedding = await asyncio.to_thread(get_embedder().embed_query, query)
        records = _store.search(
            embedding=embedding.tolist(),
            query_text=query,
            top_k=top_k,
            library=library,
            filter=filter,
        )
        return {
            "results": [
                {
                    "doc_id": r.doc_id,
                    "source": r.source,
                    "title": r.title,
                    "library": r.library,
                    "content": r.content,
                    "chunk_index": r.chunk_index,
                    "metadata": json.loads(r.metadata),
                }
                for r in records
            ]
        }
    except StoreError as e:
        return {"error": f"Search failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in search")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Tool: list_documents ──────────────────────────────────────────────────────
@mcp.tool()
async def list_documents(
    library: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """List indexed documents with metadata.

    Args:
        library: Filter by library name. Returns all libraries if None.
        limit: Maximum number of documents to return (default 20).
        offset: Number of documents to skip for pagination.

    Returns:
        Dict with 'documents' list and 'total' count.
    """
    if limit < 1 or limit > 1000:
        return {"error": "limit must be between 1 and 1000", "status": "error"}
    if offset < 0:
        return {"error": "offset must be non-negative", "status": "error"}
    try:
        docs = _store.list_documents(library=library, limit=limit, offset=offset)
        return {"documents": docs, "count": len(docs)}
    except StoreError as e:
        return {"error": f"list_documents failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in list_documents")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Tool: list_libraries ──────────────────────────────────────────────────────
@mcp.tool()
async def list_libraries() -> dict:
    """List all libraries with document and chunk counts.

    Returns:
        Dict with 'libraries' list. Each entry has library, document_count, chunk_count.
    """
    try:
        libs = _store.list_libraries()
        return {"libraries": libs}
    except StoreError as e:
        return {"error": f"list_libraries failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in list_libraries")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Tool: delete_document ─────────────────────────────────────────────────────
@mcp.tool()
async def delete_document(doc_id: str) -> dict:
    """Remove a document and all its chunks from the index.

    Args:
        doc_id: The document UUID to delete.

    Returns:
        Dict with deleted_chunks count.
    """
    if not doc_id.strip():
        return {"error": "doc_id must not be empty", "status": "error"}
    try:
        deleted = _store.delete_document(doc_id)
        return {"doc_id": doc_id, "deleted_chunks": deleted, "status": "deleted"}
    except StoreError as e:
        return {"error": f"delete_document failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in delete_document")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Tool: get_document ────────────────────────────────────────────────────────
@mcp.tool()
async def get_document(doc_id: str) -> dict:
    """Return the full Markdown text of an indexed document.

    Concatenates all chunks in order to reconstruct the document text.

    Args:
        doc_id: The document UUID to retrieve.

    Returns:
        Dict with doc_id, source, title, library, content (full text), chunk_count.
    """
    if not doc_id.strip():
        return {"error": "doc_id must not be empty", "status": "error"}
    try:
        records = _store.get_document(doc_id)
        if not records:
            return {"error": f"Document not found: {doc_id}", "status": "error"}
        first = records[0]
        full_text = "\n\n".join(r.content for r in records)
        return {
            "doc_id": doc_id,
            "source": first.source,
            "title": first.title,
            "library": first.library,
            "content": full_text,
            "chunk_count": len(records),
            "metadata": json.loads(first.metadata),
        }
    except StoreError as e:
        return {"error": f"get_document failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in get_document")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    """Start the MCP server with the configured transport."""
    logger.info("mcpvectordb starting (transport=%s)", settings.mcp_transport)

    # Pre-warm embedder at startup to avoid first-call latency
    logger.info("Pre-loading embedding model %s", settings.embedding_model)
    get_embedder()
    logger.info("Embedding model loaded. Ready.")

    if settings.mcp_transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport="sse",
            host=settings.mcp_host,
            port=settings.mcp_port,
        )


if __name__ == "__main__":  # pragma: no cover
    main()
