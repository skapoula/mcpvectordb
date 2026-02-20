"""LanceDB read/write operations and ChunkRecord schema."""

import json
import logging
from pathlib import Path

import lancedb
import numpy as np
from pydantic import BaseModel

from mcpvectordb.config import settings
from mcpvectordb.exceptions import StoreError

logger = logging.getLogger(__name__)


class ChunkRecord(BaseModel):
    """One row in the LanceDB documents table — a single embedded chunk."""

    id: str
    doc_id: str
    library: str
    source: str
    content_hash: str
    title: str
    content: str
    embedding: list[float]
    chunk_index: int
    created_at: str
    metadata: str  # JSON-serialised dict


def _open_table(uri: str, table_name: str) -> lancedb.table.Table:
    """Open (or create) the LanceDB table.

    Args:
        uri: LanceDB URI (local path or s3:// URI).
        table_name: Name of the table within the database.

    Returns:
        An open LanceDB Table object.

    Raises:
        StoreError: If the connection or table open fails.
    """
    try:
        # Expand ~ for local paths
        resolved = str(Path(uri).expanduser()) if not uri.startswith("s3://") else uri
        db = lancedb.connect(resolved)
        table_list = db.list_tables()
        existing = (
            table_list.tables if hasattr(table_list, "tables") else list(table_list)
        )
        if table_name in existing:
            return db.open_table(table_name)
        # Create table with a dummy record to establish schema, then delete it
        schema_record = {
            "id": "_schema_init_",
            "doc_id": "",
            "library": "",
            "source": "",
            "content_hash": "",
            "title": "",
            "content": "",
            "embedding": [0.0] * 768,
            "chunk_index": 0,
            "created_at": "",
            "metadata": "{}",
        }
        table = db.create_table(table_name, data=[schema_record])
        table.delete("id = '_schema_init_'")
        return table
    except Exception as e:
        raise StoreError(
            f"Failed to open LanceDB table {table_name!r} at {uri!r}"
        ) from e


class Store:
    """Provides read/write access to the LanceDB documents table.

    Each method opens a fresh connection — LanceDB is embedded and cheap to open.
    """

    def __init__(
        self,
        uri: str | None = None,
        table_name: str | None = None,
    ) -> None:
        """Initialise the store with connection parameters.

        Args:
            uri: LanceDB URI. Defaults to settings.lancedb_uri.
            table_name: Table name. Defaults to settings.lancedb_table_name.
        """
        self._uri = uri or settings.lancedb_uri
        self._table_name = table_name or settings.lancedb_table_name

    def _table(self) -> lancedb.table.Table:
        """Open and return the LanceDB table."""
        return _open_table(self._uri, self._table_name)

    def upsert_chunks(self, chunks: list[ChunkRecord]) -> None:
        """Write a list of chunk records to the store.

        Args:
            chunks: Chunk records to insert.

        Raises:
            StoreError: If the write fails.
        """
        if not chunks:
            return
        try:
            table = self._table()
            rows = [c.model_dump() for c in chunks]
            table.add(rows)
            logger.info("Upserted %d chunks (doc_id=%s)", len(chunks), chunks[0].doc_id)
        except Exception as e:
            raise StoreError(f"Failed to upsert {len(chunks)} chunks") from e

    def find_existing(self, source: str, library: str) -> tuple[str | None, str | None]:
        """Look up an existing document by (source, library) dedup key.

        Args:
            source: File path or URL string.
            library: Library name.

        Returns:
            Tuple of (doc_id, content_hash) if found, else (None, None).

        Raises:
            StoreError: If the query fails.
        """
        try:
            table = self._table()
            # Escape single quotes in source to prevent injection
            safe_source = source.replace("'", "''")
            safe_library = library.replace("'", "''")
            results = (
                table.search()
                .where(f"source = '{safe_source}' AND library = '{safe_library}'")
                .limit(1)
                .to_list()
            )
            if results:
                row = results[0]
                return row["doc_id"], row["content_hash"]
            return None, None
        except Exception as e:
            raise StoreError(f"find_existing failed for source={source!r}") from e

    def delete_document(self, doc_id: str) -> int:
        """Delete all chunks belonging to a document.

        Args:
            doc_id: The document UUID to delete.

        Returns:
            Number of rows deleted.

        Raises:
            StoreError: If the delete fails.
        """
        try:
            table = self._table()
            safe_id = doc_id.replace("'", "''")
            before = table.count_rows()
            table.delete(f"doc_id = '{safe_id}'")
            after = table.count_rows()
            deleted = before - after
            logger.info("Deleted %d chunks for doc_id=%s", deleted, doc_id)
            return deleted
        except Exception as e:
            raise StoreError(f"Failed to delete document {doc_id!r}") from e

    def search(
        self,
        embedding: list[float],
        top_k: int,
        library: str | None,
        filter: dict | None,  # noqa: A002
    ) -> list[ChunkRecord]:
        """Semantic search over stored chunks.

        # At >50k chunks, create an IVF-PQ index with table.create_index('embedding')

        Args:
            embedding: Query vector of shape (768,).
            top_k: Maximum number of results to return.
            library: Restrict search to this library if provided.
            filter: Additional metadata filters (unused in v1, reserved).

        Returns:
            List of ChunkRecord objects sorted by relevance descending.

        Raises:
            StoreError: If the search fails.
        """
        try:
            table = self._table()
            query = table.search(np.array(embedding, dtype=np.float32))
            if library is not None:
                safe_lib = library.replace("'", "''")
                query = query.where(f"library = '{safe_lib}'")
            rows = query.limit(top_k).to_list()
            return [
                ChunkRecord(**{k: v for k, v in row.items() if k != "_distance"})
                for row in rows
            ]
        except Exception as e:
            raise StoreError("Search failed") from e

    def get_document(self, doc_id: str) -> list[ChunkRecord]:
        """Return all chunks for a document, ordered by chunk_index.

        Args:
            doc_id: The document UUID.

        Returns:
            List of ChunkRecord objects sorted by chunk_index.

        Raises:
            StoreError: If the query fails.
        """
        try:
            table = self._table()
            safe_id = doc_id.replace("'", "''")
            rows = table.search().where(f"doc_id = '{safe_id}'").to_list()
            records = [
                ChunkRecord(**{k: v for k, v in row.items() if k != "_distance"})
                for row in rows
            ]
            records.sort(key=lambda r: r.chunk_index)
            return records
        except Exception as e:
            raise StoreError(f"get_document failed for doc_id={doc_id!r}") from e

    def list_documents(
        self,
        library: str | None,
        limit: int,
        offset: int,
    ) -> list[dict]:
        """List indexed documents with metadata, one entry per doc_id.

        Args:
            library: Filter by library name if provided.
            limit: Maximum number of documents to return.
            offset: Number of documents to skip.

        Returns:
            List of dicts with doc-level metadata (doc_id, source, title, library,
            content_hash, created_at, metadata, chunk_count).

        Raises:
            StoreError: If the query fails.
        """
        try:
            table = self._table()
            q = table.search()
            if library is not None:
                safe_lib = library.replace("'", "''")
                q = q.where(f"library = '{safe_lib}'")
            rows = q.to_list()

            # Group by doc_id — keep first occurrence for metadata
            seen: dict[str, dict] = {}
            for row in rows:
                did = row["doc_id"]
                if did not in seen:
                    seen[did] = {
                        "doc_id": did,
                        "source": row["source"],
                        "title": row["title"],
                        "library": row["library"],
                        "content_hash": row["content_hash"],
                        "created_at": row["created_at"],
                        "metadata": json.loads(row["metadata"]),
                        "chunk_count": 0,
                    }
                seen[did]["chunk_count"] += 1

            docs = list(seen.values())
            docs.sort(key=lambda d: d["created_at"], reverse=True)
            return docs[offset : offset + limit]
        except Exception as e:
            raise StoreError("list_documents failed") from e

    def list_libraries(self) -> list[dict]:
        """List all libraries with document and chunk counts.

        Returns:
            List of dicts with keys: library, document_count, chunk_count.

        Raises:
            StoreError: If the query fails.
        """
        try:
            table = self._table()
            rows = table.search().to_list()

            libs: dict[str, dict] = {}
            for row in rows:
                lib = row["library"]
                if lib not in libs:
                    libs[lib] = {
                        "library": lib,
                        "document_count": 0,
                        "chunk_count": 0,
                        "_docs": set(),
                    }
                libs[lib]["chunk_count"] += 1
                libs[lib]["_docs"].add(row["doc_id"])

            result = []
            for lib_data in libs.values():
                result.append(
                    {
                        "library": lib_data["library"],
                        "document_count": len(lib_data["_docs"]),
                        "chunk_count": lib_data["chunk_count"],
                    }
                )
            return result
        except Exception as e:
            raise StoreError("list_libraries failed") from e
