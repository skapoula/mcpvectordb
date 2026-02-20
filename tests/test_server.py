"""Tests for server.py — MCP tool handler contracts, validation, error responses."""

import asyncio
from unittest.mock import MagicMock

import numpy as np
import pytest


def run(coro):
    """Run a coroutine synchronously in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _use_tmp_store(tmp_path, monkeypatch):
    """Point server._store at a tmp LanceDB directory for each test."""
    from mcpvectordb.store import Store

    store = Store(uri=str(tmp_path / "lancedb"), table_name="test_documents")
    monkeypatch.setattr("mcpvectordb.server._store", store)
    return store


@pytest.fixture(autouse=True)
def _mock_ingest(monkeypatch):
    """Patch ingestor.ingest so tool tests don't run the real pipeline."""
    from mcpvectordb.ingestor import IngestResult

    async def _fake_ingest(source, library, metadata, store):
        return IngestResult(
            status="indexed",
            doc_id="doc-uuid-1234",
            source=str(source),
            library=library,
            chunk_count=3,
        )

    monkeypatch.setattr("mcpvectordb.server.ingest", _fake_ingest)


class TestIngestFileTool:
    """Tests for the ingest_file MCP tool handler."""

    @pytest.mark.unit
    def test_ingest_file_returns_status(self, tmp_path):
        """ingest_file returns a dict with status and doc_id on success."""
        from mcpvectordb import server

        f = tmp_path / "doc.pdf"
        f.write_bytes(b"content")
        result = run(server.ingest_file(path=str(f)))

        assert result["status"] == "indexed"
        assert "doc_id" in result

    @pytest.mark.unit
    def test_ingest_file_with_metadata(self, tmp_path):
        """ingest_file accepts metadata dict and returns success."""
        from mcpvectordb import server

        f = tmp_path / "doc.pdf"
        f.write_bytes(b"content")
        result = run(
            server.ingest_file(path=str(f), library="mylib", metadata={"k": "v"})
        )

        assert result["status"] == "indexed"

    @pytest.mark.unit
    def test_ingest_file_unsupported_format_returns_error(self, tmp_path, monkeypatch):
        """ingest_file with unsupported format returns an error dict, never raises."""
        from mcpvectordb import server
        from mcpvectordb.exceptions import UnsupportedFormatError

        async def _raise(*args, **kwargs):
            raise UnsupportedFormatError(".xyz not supported")

        monkeypatch.setattr("mcpvectordb.server.ingest", _raise)

        f = tmp_path / "data.xyz"
        f.write_text("content")
        result = run(server.ingest_file(path=str(f)))

        assert result["status"] == "error"
        assert "error" in result

    @pytest.mark.unit
    def test_ingest_file_ingestion_error_returns_error_dict(self, tmp_path, monkeypatch):
        """IngestionError from the pipeline returns a structured error dict (lines 64-65)."""
        from mcpvectordb import server
        from mcpvectordb.exceptions import IngestionError

        async def _raise(*args, **kwargs):
            raise IngestionError("pipeline failed")

        monkeypatch.setattr("mcpvectordb.server.ingest", _raise)

        f = tmp_path / "doc.pdf"
        f.write_bytes(b"content")
        result = run(server.ingest_file(path=str(f)))

        assert result["status"] == "error"
        assert "Ingestion failed" in result["error"]

    @pytest.mark.unit
    def test_ingest_file_unexpected_exception_returns_error_dict(self, tmp_path, monkeypatch):
        """Unexpected exception returns a structured error dict (lines 66-68)."""
        from mcpvectordb import server

        async def _raise(*args, **kwargs):
            raise RuntimeError("unexpected crash")

        monkeypatch.setattr("mcpvectordb.server.ingest", _raise)

        f = tmp_path / "doc.pdf"
        f.write_bytes(b"content")
        result = run(server.ingest_file(path=str(f)))

        assert result["status"] == "error"
        assert "Internal error" in result["error"]


class TestIngestUrlTool:
    """Tests for the ingest_url MCP tool handler."""

    @pytest.mark.unit
    def test_ingest_url_returns_status(self):
        """ingest_url with valid URL returns status dict."""
        from mcpvectordb import server

        result = run(server.ingest_url(url="https://example.com/page"))
        assert result["status"] == "indexed"

    @pytest.mark.unit
    def test_ingest_url_rejects_non_http(self):
        """ingest_url rejects URLs that don't start with http:// or https://."""
        from mcpvectordb import server

        result = run(server.ingest_url(url="ftp://example.com/file"))
        assert result["status"] == "error"
        assert "error" in result

    @pytest.mark.unit
    def test_ingest_url_ingestion_error_returns_error(self, monkeypatch):
        """IngestionError from the pipeline becomes an error dict response."""
        from mcpvectordb import server
        from mcpvectordb.exceptions import IngestionError

        async def _raise(*args, **kwargs):
            raise IngestionError("network timeout")

        monkeypatch.setattr("mcpvectordb.server.ingest", _raise)
        result = run(server.ingest_url(url="https://example.com/page"))

        assert result["status"] == "error"
        assert "network timeout" in result["error"]

    @pytest.mark.unit
    def test_ingest_url_unexpected_exception_returns_error_dict(self, monkeypatch):
        """Unexpected exception in ingest_url returns a structured error dict (lines 103-105)."""
        from mcpvectordb import server

        async def _raise(*args, **kwargs):
            raise RuntimeError("unexpected")

        monkeypatch.setattr("mcpvectordb.server.ingest", _raise)
        result = run(server.ingest_url(url="https://example.com"))

        assert result["status"] == "error"
        assert "Internal error" in result["error"]


class TestSearchTool:
    """Tests for the search MCP tool handler."""

    @pytest.mark.unit
    def test_search_empty_query_returns_error(self, monkeypatch):
        """Empty query string returns an error response."""
        from mcpvectordb import server

        result = run(server.search(query="   "))
        assert result["status"] == "error"

    @pytest.mark.unit
    def test_search_top_k_out_of_range(self):
        """top_k=0 or top_k>100 returns error."""
        from mcpvectordb import server

        assert run(server.search(query="test", top_k=0))["status"] == "error"
        assert run(server.search(query="test", top_k=101))["status"] == "error"

    @pytest.mark.unit
    def test_search_returns_results_key(self, monkeypatch):
        """Successful search returns dict with 'results' list."""
        from mcpvectordb import server

        # Patch store.search to return empty list (no real data needed)
        monkeypatch.setattr(
            "mcpvectordb.server._store",
            MagicMock(
                **{
                    "search.return_value": [],
                }
            ),
        )
        # Patch get_embedder to return a mock
        mock_emb = MagicMock()
        mock_emb.embed_query.return_value = np.random.rand(768).astype(np.float32)
        monkeypatch.setattr("mcpvectordb.server.get_embedder", lambda: mock_emb)

        result = run(server.search(query="machine learning", top_k=5))
        assert "results" in result
        assert isinstance(result["results"], list)

    @pytest.mark.unit
    def test_search_store_error_returns_error(self, monkeypatch):
        """StoreError from the store returns a structured error dict (lines 157-158)."""
        from mcpvectordb import server
        from mcpvectordb.exceptions import StoreError

        bad_store = MagicMock()
        bad_store.search.side_effect = StoreError("db failure")
        monkeypatch.setattr("mcpvectordb.server._store", bad_store)

        mock_emb = MagicMock()
        mock_emb.embed_query.return_value = np.random.rand(768).astype(np.float32)
        monkeypatch.setattr("mcpvectordb.server.get_embedder", lambda: mock_emb)

        result = run(server.search(query="test query"))
        assert result["status"] == "error"
        assert "Search failed" in result["error"]

    @pytest.mark.unit
    def test_search_unexpected_exception_returns_error(self, monkeypatch):
        """Unexpected exception in search returns a structured error dict (lines 159-161)."""
        from mcpvectordb import server

        bad_store = MagicMock()
        bad_store.search.side_effect = RuntimeError("unexpected")
        monkeypatch.setattr("mcpvectordb.server._store", bad_store)

        mock_emb = MagicMock()
        mock_emb.embed_query.return_value = np.random.rand(768).astype(np.float32)
        monkeypatch.setattr("mcpvectordb.server.get_embedder", lambda: mock_emb)

        result = run(server.search(query="test query"))
        assert result["status"] == "error"
        assert "Internal error" in result["error"]


class TestListDocumentsTool:
    """Tests for the list_documents MCP tool handler."""

    @pytest.mark.unit
    def test_list_documents_invalid_limit(self):
        """limit=0 returns error."""
        from mcpvectordb import server

        result = run(server.list_documents(limit=0))
        assert result["status"] == "error"

    @pytest.mark.unit
    def test_list_documents_negative_offset(self):
        """Negative offset returns error."""
        from mcpvectordb import server

        result = run(server.list_documents(offset=-1))
        assert result["status"] == "error"

    @pytest.mark.unit
    def test_list_documents_returns_documents_key(self):
        """Successful call returns dict with 'documents' list."""
        from mcpvectordb import server

        result = run(server.list_documents())
        assert "documents" in result
        assert isinstance(result["documents"], list)

    @pytest.mark.unit
    def test_list_documents_store_error_returns_error(self, monkeypatch):
        """StoreError from list_documents returns a structured error dict (lines 188-189)."""
        from mcpvectordb import server
        from mcpvectordb.exceptions import StoreError

        bad_store = MagicMock()
        bad_store.list_documents.side_effect = StoreError("db failure")
        monkeypatch.setattr("mcpvectordb.server._store", bad_store)

        result = run(server.list_documents())
        assert result["status"] == "error"
        assert "list_documents failed" in result["error"]

    @pytest.mark.unit
    def test_list_documents_unexpected_exception_returns_error(self, monkeypatch):
        """Unexpected exception in list_documents returns a structured error dict (lines 190-192)."""
        from mcpvectordb import server

        bad_store = MagicMock()
        bad_store.list_documents.side_effect = RuntimeError("unexpected")
        monkeypatch.setattr("mcpvectordb.server._store", bad_store)

        result = run(server.list_documents())
        assert result["status"] == "error"
        assert "Internal error" in result["error"]


class TestListLibrariesTool:
    """Tests for the list_libraries MCP tool handler."""

    @pytest.mark.unit
    def test_list_libraries_returns_libraries_key(self):
        """list_libraries returns dict with 'libraries' list."""
        from mcpvectordb import server

        result = run(server.list_libraries())
        assert "libraries" in result
        assert isinstance(result["libraries"], list)

    @pytest.mark.unit
    def test_list_libraries_store_error_returns_error(self, monkeypatch):
        """StoreError from list_libraries returns a structured error dict (lines 206-207)."""
        from mcpvectordb import server
        from mcpvectordb.exceptions import StoreError

        bad_store = MagicMock()
        bad_store.list_libraries.side_effect = StoreError("db failure")
        monkeypatch.setattr("mcpvectordb.server._store", bad_store)

        result = run(server.list_libraries())
        assert result["status"] == "error"
        assert "list_libraries failed" in result["error"]

    @pytest.mark.unit
    def test_list_libraries_unexpected_exception_returns_error(self, monkeypatch):
        """Unexpected exception in list_libraries returns a structured error dict (lines 208-210)."""
        from mcpvectordb import server

        bad_store = MagicMock()
        bad_store.list_libraries.side_effect = RuntimeError("unexpected")
        monkeypatch.setattr("mcpvectordb.server._store", bad_store)

        result = run(server.list_libraries())
        assert result["status"] == "error"
        assert "Internal error" in result["error"]


class TestDeleteDocumentTool:
    """Tests for the delete_document MCP tool handler."""

    @pytest.mark.unit
    def test_delete_empty_doc_id_returns_error(self):
        """Empty doc_id string returns error."""
        from mcpvectordb import server

        result = run(server.delete_document(doc_id=""))
        assert result["status"] == "error"

    @pytest.mark.unit
    def test_delete_nonexistent_doc_returns_deleted(self):
        """Deleting a non-existent doc_id returns status='deleted' with 0 chunks."""
        from mcpvectordb import server

        result = run(server.delete_document(doc_id="does-not-exist"))
        assert result["status"] == "deleted"
        assert result["deleted_chunks"] == 0

    @pytest.mark.unit
    def test_delete_document_store_error_returns_error(self, monkeypatch):
        """StoreError from delete_document returns a structured error dict (lines 229-230)."""
        from mcpvectordb import server
        from mcpvectordb.exceptions import StoreError

        bad_store = MagicMock()
        bad_store.delete_document.side_effect = StoreError("db failure")
        monkeypatch.setattr("mcpvectordb.server._store", bad_store)

        result = run(server.delete_document(doc_id="valid-id"))
        assert result["status"] == "error"
        assert "delete_document failed" in result["error"]

    @pytest.mark.unit
    def test_delete_document_unexpected_exception_returns_error(self, monkeypatch):
        """Unexpected exception in delete_document returns a structured error dict (lines 231-233)."""
        from mcpvectordb import server

        bad_store = MagicMock()
        bad_store.delete_document.side_effect = RuntimeError("unexpected")
        monkeypatch.setattr("mcpvectordb.server._store", bad_store)

        result = run(server.delete_document(doc_id="valid-id"))
        assert result["status"] == "error"
        assert "Internal error" in result["error"]


class TestGetDocumentTool:
    """Tests for the get_document MCP tool handler."""

    @pytest.mark.unit
    def test_get_document_empty_id_returns_error(self):
        """Empty doc_id returns error."""
        from mcpvectordb import server

        result = run(server.get_document(doc_id=""))
        assert result["status"] == "error"

    @pytest.mark.unit
    def test_get_document_missing_returns_error(self):
        """get_document for unknown doc_id returns error dict."""
        from mcpvectordb import server

        result = run(server.get_document(doc_id="not-a-real-uuid"))
        assert result["status"] == "error"
        assert "not found" in result["error"].lower() or "error" in result

    @pytest.mark.integration
    def test_get_document_returns_full_content(self, _use_tmp_store):
        """get_document returns content and metadata for an existing document (lines 255-265)."""
        import json
        import uuid
        from datetime import UTC, datetime
        from mcpvectordb import server
        from mcpvectordb.store import ChunkRecord

        store = _use_tmp_store
        doc_id = str(uuid.uuid4())
        record = ChunkRecord(
            id=str(uuid.uuid4()),
            doc_id=doc_id,
            library="default",
            source="tests/sample.pdf",
            content_hash="testhash",
            title="Test Document",
            content="Hello World chunk content.",
            embedding=[0.1] * 768,
            chunk_index=0,
            created_at=datetime.now(UTC).isoformat(),
            metadata=json.dumps({"author": "Test"}),
        )
        store.upsert_chunks([record])

        result = run(server.get_document(doc_id=doc_id))

        assert result["doc_id"] == doc_id
        assert result["content"] == "Hello World chunk content."
        assert result["chunk_count"] == 1
        assert result["metadata"] == {"author": "Test"}

    @pytest.mark.unit
    def test_get_document_store_error_returns_error(self, monkeypatch):
        """StoreError from get_document returns a structured error dict (lines 266-267)."""
        from mcpvectordb import server
        from mcpvectordb.exceptions import StoreError

        bad_store = MagicMock()
        bad_store.get_document.side_effect = StoreError("db failure")
        monkeypatch.setattr("mcpvectordb.server._store", bad_store)

        result = run(server.get_document(doc_id="valid-id"))
        assert result["status"] == "error"
        assert "get_document failed" in result["error"]

    @pytest.mark.unit
    def test_get_document_unexpected_exception_returns_error(self, monkeypatch):
        """Unexpected exception in get_document returns a structured error dict (lines 268-270)."""
        from mcpvectordb import server

        bad_store = MagicMock()
        bad_store.get_document.side_effect = RuntimeError("unexpected")
        monkeypatch.setattr("mcpvectordb.server._store", bad_store)

        result = run(server.get_document(doc_id="valid-id"))
        assert result["status"] == "error"
        assert "Internal error" in result["error"]


class TestMainFunction:
    """Tests for the main() entry point function."""

    @pytest.mark.unit
    def test_main_runs_with_stdio_transport(self, monkeypatch):
        """main() calls mcp.run(transport='stdio') when configured (lines 276-284)."""
        import mcpvectordb.server as server_mod
        import mcpvectordb.config as config_mod

        mock_run = MagicMock()
        monkeypatch.setattr(server_mod.mcp, "run", mock_run)
        monkeypatch.setattr("mcpvectordb.server.get_embedder", MagicMock())
        monkeypatch.setattr(config_mod.settings, "mcp_transport", "stdio")

        server_mod.main()

        mock_run.assert_called_once_with(transport="stdio")

    @pytest.mark.unit
    def test_main_runs_with_sse_transport(self, monkeypatch):
        """main() calls mcp.run with SSE parameters when transport='sse' (lines 285-290)."""
        import mcpvectordb.server as server_mod
        import mcpvectordb.config as config_mod

        mock_run = MagicMock()
        monkeypatch.setattr(server_mod.mcp, "run", mock_run)
        monkeypatch.setattr("mcpvectordb.server.get_embedder", MagicMock())
        monkeypatch.setattr(config_mod.settings, "mcp_transport", "sse")
        monkeypatch.setattr(config_mod.settings, "mcp_host", "0.0.0.0")
        monkeypatch.setattr(config_mod.settings, "mcp_port", 9000)

        server_mod.main()

        mock_run.assert_called_once_with(transport="sse", host="0.0.0.0", port=9000)
