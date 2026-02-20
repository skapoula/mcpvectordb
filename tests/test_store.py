"""Tests for store.py — LanceDB read/write/delete, schema, dedup scenarios."""

import json
import uuid
from datetime import UTC, datetime

import numpy as np
import pytest

from mcpvectordb.config import settings
from mcpvectordb.store import ChunkRecord


def _make_chunk(
    *,
    doc_id: str | None = None,
    library: str = "default",
    source: str = "test://file.pdf",
    content: str = "Some test content for the chunk.",
    chunk_index: int = 0,
    content_hash: str = "abc123",
    embedding: list[float] | None = None,
    file_type: str = "pdf",
    last_modified: str = "",
    page: int = 0,
) -> ChunkRecord:
    """Build a minimal ChunkRecord for testing."""
    return ChunkRecord(
        id=str(uuid.uuid4()),
        doc_id=doc_id or str(uuid.uuid4()),
        library=library,
        source=source,
        content_hash=content_hash,
        title="Test Document",
        content=content,
        embedding=embedding or np.random.rand(settings.embedding_dimension).astype(np.float32).tolist(),
        chunk_index=chunk_index,
        created_at=datetime.now(UTC).isoformat(),
        metadata=json.dumps({}),
        file_type=file_type,
        last_modified=last_modified,
        page=page,
    )


class TestStoreUpsertAndRetrieve:
    """Basic write and retrieve operations."""

    @pytest.mark.integration
    def test_upsert_and_get_document(self, store):
        """Inserted chunks can be retrieved by doc_id."""
        doc_id = str(uuid.uuid4())
        chunks = [_make_chunk(doc_id=doc_id, chunk_index=i) for i in range(3)]
        store.upsert_chunks(chunks)

        retrieved = store.get_document(doc_id)
        assert len(retrieved) == 3
        assert [r.chunk_index for r in retrieved] == [0, 1, 2]

    @pytest.mark.integration
    def test_get_document_returns_ordered_chunks(self, store):
        """Chunks come back sorted by chunk_index regardless of insert order."""
        doc_id = str(uuid.uuid4())
        # Insert in reverse order
        chunks = [_make_chunk(doc_id=doc_id, chunk_index=i) for i in reversed(range(5))]
        store.upsert_chunks(chunks)

        retrieved = store.get_document(doc_id)
        assert [r.chunk_index for r in retrieved] == [0, 1, 2, 3, 4]

    @pytest.mark.integration
    def test_get_document_missing_returns_empty(self, store):
        """get_document for an unknown doc_id returns []."""
        result = store.get_document(str(uuid.uuid4()))
        assert result == []

    @pytest.mark.integration
    def test_upsert_empty_list_is_noop(self, store):
        """upsert_chunks with an empty list does not raise."""
        store.upsert_chunks([])  # Should not raise


class TestStoreSearch:
    """Semantic search tests."""

    @pytest.mark.integration
    def test_search_empty_table_returns_empty(self, store):
        """Searching an empty table returns [] without raising."""
        embedding = np.random.rand(settings.embedding_dimension).astype(np.float32).tolist()
        result = store.search(
            embedding=embedding,
            query_text="test query",
            top_k=5,
            library=None,
            filter=None,
        )
        assert result == []

    @pytest.mark.integration
    def test_search_returns_at_most_top_k(self, store):
        """Search returns no more than top_k results."""
        doc_id = str(uuid.uuid4())
        chunks = [_make_chunk(doc_id=doc_id, chunk_index=i) for i in range(10)]
        store.upsert_chunks(chunks)

        embedding = np.random.rand(settings.embedding_dimension).astype(np.float32).tolist()
        result = store.search(
            embedding=embedding,
            query_text="test query",
            top_k=3,
            library=None,
            filter=None,
        )
        assert len(result) <= 3

    @pytest.mark.integration
    def test_search_filters_by_library(self, store):
        """Search restricted to a library does not return chunks from other libs."""
        doc_a = str(uuid.uuid4())
        doc_b = str(uuid.uuid4())
        chunks_a = [
            _make_chunk(doc_id=doc_a, library="lib_a", chunk_index=i) for i in range(3)
        ]
        chunks_b = [
            _make_chunk(doc_id=doc_b, library="lib_b", chunk_index=i) for i in range(3)
        ]
        store.upsert_chunks(chunks_a + chunks_b)

        embedding = np.random.rand(settings.embedding_dimension).astype(np.float32).tolist()
        result = store.search(
            embedding=embedding,
            query_text="test query",
            top_k=10,
            library="lib_a",
            filter=None,
        )
        assert all(r.library == "lib_a" for r in result)


class TestStoreDelete:
    """Document deletion tests."""

    @pytest.mark.integration
    def test_delete_removes_chunks(self, store):
        """delete_document removes all chunks for a doc_id."""
        doc_id = str(uuid.uuid4())
        store.upsert_chunks(
            [_make_chunk(doc_id=doc_id, chunk_index=i) for i in range(4)]
        )

        store.delete_document(doc_id)
        assert store.get_document(doc_id) == []

    @pytest.mark.integration
    def test_delete_returns_chunk_count(self, store):
        """delete_document returns the number of chunks deleted."""
        doc_id = str(uuid.uuid4())
        store.upsert_chunks(
            [_make_chunk(doc_id=doc_id, chunk_index=i) for i in range(3)]
        )

        deleted = store.delete_document(doc_id)
        assert deleted == 3

    @pytest.mark.integration
    def test_delete_nonexistent_doc_returns_zero(self, store):
        """Deleting a doc_id that doesn't exist returns 0."""
        deleted = store.delete_document(str(uuid.uuid4()))
        assert deleted == 0

    @pytest.mark.integration
    def test_delete_does_not_affect_other_docs(self, store):
        """Deleting one document leaves others intact."""
        doc_a = str(uuid.uuid4())
        doc_b = str(uuid.uuid4())
        store.upsert_chunks([_make_chunk(doc_id=doc_a, chunk_index=0)])
        store.upsert_chunks([_make_chunk(doc_id=doc_b, chunk_index=0)])

        store.delete_document(doc_a)
        assert store.get_document(doc_a) == []
        assert len(store.get_document(doc_b)) == 1


class TestStoreDedup:
    """Deduplication logic — find_existing with (source, library) key."""

    @pytest.mark.integration
    def test_find_existing_returns_none_when_absent(self, store):
        """find_existing returns (None, None) for an unknown (source, library)."""
        doc_id, content_hash = store.find_existing("no-such-source", "default")
        assert doc_id is None
        assert content_hash is None

    @pytest.mark.integration
    def test_find_existing_returns_doc_id_and_hash(self, store):
        """find_existing returns correct doc_id and hash after insert."""
        doc_id = str(uuid.uuid4())
        source = "file:///path/to/doc.pdf"
        library = "mylib"
        c = _make_chunk(
            doc_id=doc_id, source=source, library=library, content_hash="deadbeef"
        )
        store.upsert_chunks([c])

        found_id, found_hash = store.find_existing(source, library)
        assert found_id == doc_id
        assert found_hash == "deadbeef"

    @pytest.mark.integration
    def test_same_source_different_library_not_found(self, store):
        """Same source in a different library is not returned."""
        doc_id = str(uuid.uuid4())
        source = "file:///shared.pdf"
        store.upsert_chunks(
            [_make_chunk(doc_id=doc_id, source=source, library="lib_a")]
        )

        found_id, found_hash = store.find_existing(source, "lib_b")
        assert found_id is None
        assert found_hash is None

    @pytest.mark.integration
    def test_dedup_scenario_same_hash_same_source_and_library(self, store):
        """Scenario 1: same (source, library) + same hash → find_existing detects it."""
        doc_id = str(uuid.uuid4())
        source = "file:///doc.pdf"
        library = "default"
        content_hash = "hash_aaa"

        store.upsert_chunks(
            [
                _make_chunk(
                    doc_id=doc_id,
                    source=source,
                    library=library,
                    content_hash=content_hash,
                )
            ]
        )

        found_id, found_hash = store.find_existing(source, library)
        assert found_id == doc_id
        assert found_hash == content_hash  # caller can compare and skip

    @pytest.mark.integration
    def test_dedup_scenario_different_hash_same_source_and_library(self, store):
        """Scenario 2: same (source, library) + different hash → replaced."""
        doc_id = str(uuid.uuid4())
        source = "file:///doc.pdf"
        library = "default"

        store.upsert_chunks(
            [
                _make_chunk(
                    doc_id=doc_id,
                    source=source,
                    library=library,
                    content_hash="old_hash",
                )
            ]
        )

        found_id, found_hash = store.find_existing(source, library)
        assert found_id == doc_id
        # caller sees it differs from new_hash → replace
        assert found_hash == "old_hash"

        # Simulate replacement
        store.delete_document(doc_id)
        new_doc_id = str(uuid.uuid4())
        store.upsert_chunks(
            [
                _make_chunk(
                    doc_id=new_doc_id,
                    source=source,
                    library=library,
                    content_hash="new_hash",
                )
            ]
        )

        found_id2, found_hash2 = store.find_existing(source, library)
        assert found_id2 == new_doc_id
        assert found_hash2 == "new_hash"

    @pytest.mark.integration
    def test_dedup_scenario_same_source_different_libraries_independent(self, store):
        """Scenario 3: same source, different libraries are independently indexed."""
        source = "file:///shared.pdf"
        doc_a = str(uuid.uuid4())
        doc_b = str(uuid.uuid4())

        ca = _make_chunk(
            doc_id=doc_a, source=source, library="lib_a", content_hash="hash_a"
        )
        cb = _make_chunk(
            doc_id=doc_b, source=source, library="lib_b", content_hash="hash_b"
        )
        store.upsert_chunks([ca])
        store.upsert_chunks([cb])

        id_a, hash_a = store.find_existing(source, "lib_a")
        id_b, hash_b = store.find_existing(source, "lib_b")

        assert id_a == doc_a
        assert hash_a == "hash_a"
        assert id_b == doc_b
        assert hash_b == "hash_b"

        # Deleting lib_a does not affect lib_b
        store.delete_document(doc_a)
        id_a2, _ = store.find_existing(source, "lib_a")
        id_b2, _ = store.find_existing(source, "lib_b")
        assert id_a2 is None
        assert id_b2 == doc_b


class TestListDocuments:
    """Tests for list_documents and list_libraries."""

    @pytest.mark.integration
    def test_list_documents_empty(self, store):
        """list_documents on empty store returns empty list."""
        assert store.list_documents(library=None, limit=20, offset=0) == []

    @pytest.mark.integration
    def test_list_documents_returns_one_per_doc(self, store):
        """list_documents groups chunks and returns one entry per document."""
        doc_id = str(uuid.uuid4())
        store.upsert_chunks(
            [_make_chunk(doc_id=doc_id, chunk_index=i) for i in range(5)]
        )

        docs = store.list_documents(library=None, limit=20, offset=0)
        assert len(docs) == 1
        assert docs[0]["doc_id"] == doc_id
        assert docs[0]["chunk_count"] == 5

    @pytest.mark.integration
    def test_list_libraries_empty(self, store):
        """list_libraries on empty store returns empty list."""
        assert store.list_libraries() == []

    @pytest.mark.integration
    def test_list_libraries_counts(self, store):
        """list_libraries counts documents and chunks correctly."""
        doc_a = str(uuid.uuid4())
        doc_b = str(uuid.uuid4())
        store.upsert_chunks(
            [_make_chunk(doc_id=doc_a, library="lib", chunk_index=i) for i in range(3)]
        )
        store.upsert_chunks(
            [_make_chunk(doc_id=doc_b, library="lib", chunk_index=i) for i in range(2)]
        )

        libs = store.list_libraries()
        assert len(libs) == 1
        assert libs[0]["library"] == "lib"
        assert libs[0]["document_count"] == 2
        assert libs[0]["chunk_count"] == 5

    @pytest.mark.integration
    def test_list_documents_filtered_by_library(self, store):
        """list_documents with library filter returns only docs from that library (lines 263-264)."""
        doc_a = str(uuid.uuid4())
        doc_b = str(uuid.uuid4())
        store.upsert_chunks([_make_chunk(doc_id=doc_a, library="lib_x", chunk_index=0)])
        store.upsert_chunks([_make_chunk(doc_id=doc_b, library="lib_y", chunk_index=0)])

        docs = store.list_documents(library="lib_x", limit=20, offset=0)

        assert len(docs) == 1
        assert docs[0]["doc_id"] == doc_a
        assert docs[0]["library"] == "lib_x"


class TestStoreErrors:
    """Tests that StoreError is raised when LanceDB operations fail."""

    @pytest.mark.unit
    def test_open_table_raises_store_error_on_connect_failure(self, monkeypatch):
        """_open_table raises StoreError when lancedb.connect fails (lines 73-74)."""
        from unittest.mock import MagicMock

        import lancedb

        from mcpvectordb.exceptions import StoreError
        from mcpvectordb.store import _open_table

        monkeypatch.setattr(
            lancedb, "connect", MagicMock(side_effect=RuntimeError("no db"))
        )

        with pytest.raises(StoreError):
            _open_table("/invalid/path", "table")

    @pytest.mark.unit
    def test_upsert_chunks_raises_store_error(self, store, monkeypatch):
        """upsert_chunks raises StoreError when the LanceDB write fails (lines 119-120)."""
        from unittest.mock import MagicMock

        from mcpvectordb.exceptions import StoreError

        monkeypatch.setattr(
            store, "_table", MagicMock(side_effect=RuntimeError("write error"))
        )

        with pytest.raises(StoreError):
            store.upsert_chunks([_make_chunk()])

    @pytest.mark.unit
    def test_find_existing_raises_store_error(self, store, monkeypatch):
        """find_existing raises StoreError on LanceDB failure (lines 150-151)."""
        from unittest.mock import MagicMock

        from mcpvectordb.exceptions import StoreError

        monkeypatch.setattr(
            store, "_table", MagicMock(side_effect=RuntimeError("query error"))
        )

        with pytest.raises(StoreError):
            store.find_existing("source", "library")

    @pytest.mark.unit
    def test_delete_document_raises_store_error(self, store, monkeypatch):
        """delete_document raises StoreError on LanceDB failure (lines 174-175)."""
        from unittest.mock import MagicMock

        from mcpvectordb.exceptions import StoreError

        monkeypatch.setattr(
            store, "_table", MagicMock(side_effect=RuntimeError("delete error"))
        )

        with pytest.raises(StoreError):
            store.delete_document("some-id")

    @pytest.mark.unit
    def test_search_raises_store_error(self, store, monkeypatch):
        """search raises StoreError on LanceDB failure (lines 211-212)."""
        from unittest.mock import MagicMock

        from mcpvectordb.exceptions import StoreError

        monkeypatch.setattr(
            store, "_table", MagicMock(side_effect=RuntimeError("search error"))
        )

        with pytest.raises(StoreError):
            store.search(
                embedding=np.random.rand(settings.embedding_dimension).tolist(),
                query_text="test query",
                top_k=5,
                library=None,
                filter=None,
            )

    @pytest.mark.unit
    def test_get_document_raises_store_error(self, store, monkeypatch):
        """get_document raises StoreError on LanceDB failure (lines 236-237)."""
        from unittest.mock import MagicMock

        from mcpvectordb.exceptions import StoreError

        monkeypatch.setattr(
            store, "_table", MagicMock(side_effect=RuntimeError("fetch error"))
        )

        with pytest.raises(StoreError):
            store.get_document("some-id")

    @pytest.mark.unit
    def test_list_documents_raises_store_error(self, store, monkeypatch):
        """list_documents raises StoreError on LanceDB failure (lines 287-288)."""
        from unittest.mock import MagicMock

        from mcpvectordb.exceptions import StoreError

        monkeypatch.setattr(
            store, "_table", MagicMock(side_effect=RuntimeError("list error"))
        )

        with pytest.raises(StoreError):
            store.list_documents(library=None, limit=20, offset=0)

    @pytest.mark.unit
    def test_list_libraries_raises_store_error(self, store, monkeypatch):
        """list_libraries raises StoreError on LanceDB failure (lines 326-327)."""
        from unittest.mock import MagicMock

        from mcpvectordb.exceptions import StoreError

        monkeypatch.setattr(
            store, "_table", MagicMock(side_effect=RuntimeError("list error"))
        )

        with pytest.raises(StoreError):
            store.list_libraries()


class TestStoreFilter:
    """Tests for the filter parameter on Store.search()."""

    @pytest.mark.integration
    def test_filter_by_file_type(self, store):
        """filter={'file_type': 'pdf'} excludes chunks with a different file_type."""
        doc_pdf = str(uuid.uuid4())
        doc_html = str(uuid.uuid4())
        store.upsert_chunks(
            [_make_chunk(doc_id=doc_pdf, file_type="pdf", content="pdf content here")]
        )
        store.upsert_chunks(
            [_make_chunk(doc_id=doc_html, file_type="html", content="html content here")]
        )

        embedding = np.random.rand(settings.embedding_dimension).astype(np.float32).tolist()
        results = store.search(
            embedding=embedding,
            query_text="content",
            top_k=10,
            library=None,
            filter={"file_type": "pdf"},
        )
        assert results
        assert all(r.file_type == "pdf" for r in results)

    @pytest.mark.integration
    def test_filter_by_page(self, store):
        """filter={'page': 2} returns only chunks with page == 2."""
        doc_id = str(uuid.uuid4())
        store.upsert_chunks(
            [
                _make_chunk(doc_id=doc_id, chunk_index=0, page=1, content="page one text"),
                _make_chunk(doc_id=doc_id, chunk_index=1, page=2, content="page two text"),
            ]
        )

        embedding = np.random.rand(settings.embedding_dimension).astype(np.float32).tolist()
        results = store.search(
            embedding=embedding,
            query_text="page",
            top_k=10,
            library=None,
            filter={"page": 2},
        )
        assert results
        assert all(r.page == 2 for r in results)

    @pytest.mark.integration
    def test_filter_combined_with_library(self, store):
        """library param and filter dict are AND-ed together."""
        doc_a = str(uuid.uuid4())
        doc_b = str(uuid.uuid4())
        store.upsert_chunks(
            [_make_chunk(doc_id=doc_a, library="lib_a", file_type="pdf")]
        )
        store.upsert_chunks(
            [_make_chunk(doc_id=doc_b, library="lib_a", file_type="html")]
        )

        embedding = np.random.rand(settings.embedding_dimension).astype(np.float32).tolist()
        results = store.search(
            embedding=embedding,
            query_text="test",
            top_k=10,
            library="lib_a",
            filter={"file_type": "pdf"},
        )
        assert all(r.library == "lib_a" and r.file_type == "pdf" for r in results)

    @pytest.mark.unit
    def test_invalid_filter_key_raises_store_error(self, store, monkeypatch):
        """A filter key with invalid characters raises StoreError."""
        from mcpvectordb.exceptions import StoreError

        monkeypatch.setattr(
            store, "_table", lambda: None
        )  # table not needed — error is raised before use
        embedding = np.random.rand(settings.embedding_dimension).astype(np.float32).tolist()
        with pytest.raises(StoreError):
            store.search(
                embedding=embedding,
                query_text="test",
                top_k=5,
                library=None,
                filter={"bad-key; DROP TABLE": "value"},
            )

    @pytest.mark.unit
    def test_build_where_clause_library_only(self):
        """_build_where_clause with library and no filter returns library condition."""
        from mcpvectordb.store import _build_where_clause

        result = _build_where_clause("mylib", None)
        assert result == "library = 'mylib'"

    @pytest.mark.unit
    def test_build_where_clause_filter_only(self):
        """_build_where_clause with no library and a filter returns filter condition."""
        from mcpvectordb.store import _build_where_clause

        result = _build_where_clause(None, {"file_type": "pdf"})
        assert result == "file_type = 'pdf'"

    @pytest.mark.unit
    def test_build_where_clause_combined(self):
        """_build_where_clause combines library and filter with AND."""
        from mcpvectordb.store import _build_where_clause

        result = _build_where_clause("lib_a", {"file_type": "pdf"})
        assert result == "library = 'lib_a' AND file_type = 'pdf'"

    @pytest.mark.unit
    def test_build_where_clause_none_when_empty(self):
        """_build_where_clause returns None when both library and filter are empty."""
        from mcpvectordb.store import _build_where_clause

        assert _build_where_clause(None, None) is None
        assert _build_where_clause(None, {}) is None

    @pytest.mark.unit
    def test_build_where_clause_int_value_unquoted(self):
        """Integer filter values are not quoted in the WHERE clause."""
        from mcpvectordb.store import _build_where_clause

        result = _build_where_clause(None, {"page": 3})
        assert result == "page = 3"

    @pytest.mark.unit
    def test_build_where_clause_escapes_single_quotes(self):
        """Single quotes in values are escaped to prevent SQL injection."""
        from mcpvectordb.store import _build_where_clause

        result = _build_where_clause("lib's", {"file_type": "it's a pdf"})
        assert "lib''s" in result
        assert "it''s a pdf" in result


class TestStoreSchemaMigration:
    """Tests for _migrate_table — adding new columns to pre-existing tables."""

    @pytest.mark.integration
    def test_migrate_adds_new_columns_to_old_table(self, lancedb_dir):
        """_open_table adds file_type, last_modified, page to a pre-existing table."""
        import lancedb as _lancedb

        from mcpvectordb.store import _open_table

        # Create a table with the old schema (no new fields)
        db = _lancedb.connect(str(lancedb_dir))
        db.create_table(
            "old_docs",
            data=[
                {
                    "id": "seed",
                    "doc_id": "d1",
                    "library": "default",
                    "source": "test.pdf",
                    "content_hash": "abc",
                    "title": "T",
                    "content": "c",
                    "embedding": [0.0] * settings.embedding_dimension,
                    "chunk_index": 0,
                    "created_at": "2024-01-01",
                    "metadata": "{}",
                }
            ],
        )

        # Opening via _open_table must trigger migration
        table = _open_table(str(lancedb_dir), "old_docs")
        col_names = {field.name for field in table.schema}

        assert "file_type" in col_names
        assert "last_modified" in col_names
        assert "page" in col_names

    @pytest.mark.integration
    def test_migrate_is_idempotent(self, lancedb_dir):
        """Opening an already-migrated table a second time does not raise."""
        from mcpvectordb.store import _open_table

        # First open creates the table with the current schema
        _open_table(str(lancedb_dir), "docs")
        # Second open should run migration but find nothing to add
        _open_table(str(lancedb_dir), "docs")


class TestStoreHybridSearch:
    """Hybrid search (BM25 + vector) tests."""

    @pytest.mark.integration
    def test_hybrid_finds_exact_term(self, store):
        """Hybrid search retrieves a document by an exact term BM25 can match."""
        doc_id = str(uuid.uuid4())
        store.upsert_chunks(
            [_make_chunk(doc_id=doc_id, content="deployment error code E-4021 in prod")]
        )
        embedding = np.random.rand(settings.embedding_dimension).astype(np.float32).tolist()
        results = store.search(
            embedding=embedding,
            query_text="E-4021",
            top_k=5,
            library=None,
            filter=None,
        )
        assert any("E-4021" in r.content for r in results)

    @pytest.mark.integration
    def test_hybrid_empty_table_returns_empty(self, store):
        """Hybrid search on empty table returns [] without raising."""
        embedding = np.random.rand(settings.embedding_dimension).astype(np.float32).tolist()
        results = store.search(
            embedding=embedding,
            query_text="anything",
            top_k=5,
            library=None,
            filter=None,
        )
        assert results == []

    @pytest.mark.integration
    def test_hybrid_respects_library_filter(self, store):
        """Hybrid search with library filter excludes results from other libraries."""
        doc_a, doc_b = str(uuid.uuid4()), str(uuid.uuid4())
        store.upsert_chunks(
            [_make_chunk(doc_id=doc_a, library="lib_a", content="alpha omega delta")]
        )
        store.upsert_chunks(
            [_make_chunk(doc_id=doc_b, library="lib_b", content="alpha omega delta")]
        )
        embedding = np.random.rand(settings.embedding_dimension).astype(np.float32).tolist()
        results = store.search(
            embedding=embedding,
            query_text="alpha omega",
            top_k=10,
            library="lib_a",
            filter=None,
        )
        assert all(r.library == "lib_a" for r in results)

    @pytest.mark.unit
    def test_hybrid_falls_back_to_vector_when_disabled(self, store, monkeypatch):
        """Disabling hybrid_search_enabled falls back to vector-only search."""
        import mcpvectordb.store as store_module

        monkeypatch.setattr(store_module.settings, "hybrid_search_enabled", False)
        doc_id = str(uuid.uuid4())
        store.upsert_chunks([_make_chunk(doc_id=doc_id)])
        embedding = np.random.rand(settings.embedding_dimension).astype(np.float32).tolist()
        results = store.search(
            embedding=embedding,
            query_text="test",
            top_k=5,
            library=None,
            filter=None,
        )
        assert isinstance(results, list)

    @pytest.mark.unit
    def test_refine_factor_applied(self, store, monkeypatch):
        """search() calls refine_factor() with the configured value on both paths."""
        from unittest.mock import MagicMock, patch

        import mcpvectordb.store as store_module

        doc_id = str(uuid.uuid4())
        store.upsert_chunks([_make_chunk(doc_id=doc_id)])

        captured: list[int] = []

        original_table = store._table

        def patched_table():
            tbl = original_table()
            original_search = tbl.search

            def recording_search(*args, **kwargs):
                builder = original_search(*args, **kwargs)
                original_rf = builder.refine_factor

                def capture_rf(n):
                    captured.append(n)
                    return original_rf(n)

                builder.refine_factor = capture_rf
                return builder

            tbl.search = recording_search
            return tbl

        monkeypatch.setattr(store_module.settings, "hybrid_search_enabled", False)
        monkeypatch.setattr(store, "_table", patched_table)
        embedding = np.random.rand(settings.embedding_dimension).astype(np.float32).tolist()
        store.search(
            embedding=embedding,
            query_text="test",
            top_k=5,
            library=None,
            filter=None,
        )
        assert captured == [settings.search_refine_factor]
