"""Tests for server.py — MCP tool handler contracts, validation, error responses."""

import asyncio
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest
from starlette.testclient import TestClient

from mcpvectordb.config import settings


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

    @pytest.mark.unit
    def test_ingest_file_tilde_path_is_expanded(self, monkeypatch):
        """ingest_file with a ~/... path calls ingest with an expanded absolute path."""
        from pathlib import Path

        from mcpvectordb import server
        from mcpvectordb.ingestor import IngestResult

        captured: dict = {}

        async def _spy(source, library, metadata, store):
            captured["source"] = source
            return IngestResult(
                status="indexed",
                doc_id="tilde-doc",
                source=str(source),
                library=library,
                chunk_count=1,
            )

        monkeypatch.setattr("mcpvectordb.server.ingest", _spy)
        run(server.ingest_file(path="~/docs/report.pdf"))

        source = captured["source"]
        assert isinstance(source, Path)
        # The tilde must have been expanded — the resolved path is absolute
        assert source.is_absolute()
        assert "~" not in str(source)


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


class TestIngestContentTool:
    """Tests for the ingest_content MCP tool handler."""

    @pytest.mark.unit
    def test_returns_indexed_on_new_content(self, monkeypatch):
        """ingest_content returns status='indexed' with doc_id and chunk_count on new content."""
        from mcpvectordb import server
        from mcpvectordb.ingestor import IngestResult

        async def _fake(content, source, library, metadata, store):
            return IngestResult(
                status="indexed",
                doc_id="content-doc-id",
                source=source,
                library=library,
                chunk_count=3,
            )

        monkeypatch.setattr("mcpvectordb.server._ingest_content", _fake)
        result = run(server.ingest_content(content="Hello world", source="test.txt"))

        assert result["status"] == "indexed"
        assert result["doc_id"] == "content-doc-id"
        assert result["chunk_count"] == 3

    @pytest.mark.unit
    def test_returns_skipped_for_duplicate(self, monkeypatch):
        """ingest_content returns status='skipped' and chunk_count=0 for duplicate content."""
        from mcpvectordb import server
        from mcpvectordb.ingestor import IngestResult

        async def _fake(content, source, library, metadata, store):
            return IngestResult(
                status="skipped",
                doc_id="existing-doc-id",
                source=source,
                library=library,
                chunk_count=0,
            )

        monkeypatch.setattr("mcpvectordb.server._ingest_content", _fake)
        result = run(server.ingest_content(content="Hello world", source="test.txt"))

        assert result["status"] == "skipped"
        assert result["chunk_count"] == 0

    @pytest.mark.unit
    def test_returns_replaced_for_updated_content(self, monkeypatch):
        """ingest_content returns status='replaced' when content hash has changed."""
        from mcpvectordb import server
        from mcpvectordb.ingestor import IngestResult

        async def _fake(content, source, library, metadata, store):
            return IngestResult(
                status="replaced",
                doc_id="new-doc-id",
                source=source,
                library=library,
                chunk_count=2,
            )

        monkeypatch.setattr("mcpvectordb.server._ingest_content", _fake)
        result = run(server.ingest_content(content="Updated content", source="test.txt"))

        assert result["status"] == "replaced"
        assert "doc_id" in result

    @pytest.mark.unit
    def test_empty_content_returns_error(self):
        """Empty or whitespace-only content returns an error dict without calling _ingest_content."""
        from mcpvectordb import server

        result_empty = run(server.ingest_content(content="", source="test.txt"))
        assert result_empty["status"] == "error"
        assert "error" in result_empty

        result_whitespace = run(server.ingest_content(content="   ", source="test.txt"))
        assert result_whitespace["status"] == "error"
        assert "error" in result_whitespace

    @pytest.mark.unit
    def test_ingestion_error_returns_error_dict(self, monkeypatch):
        """IngestionError from _ingest_content returns a structured error dict."""
        from mcpvectordb import server
        from mcpvectordb.exceptions import IngestionError

        async def _raise(*args, **kwargs):
            raise IngestionError("pipeline failed")

        monkeypatch.setattr("mcpvectordb.server._ingest_content", _raise)
        result = run(server.ingest_content(content="Hello world", source="test.txt"))

        assert result["status"] == "error"
        assert "Ingestion failed" in result["error"]

    @pytest.mark.unit
    def test_unexpected_exception_returns_error_dict(self, monkeypatch):
        """Unexpected exception from _ingest_content returns a structured error dict."""
        from mcpvectordb import server

        async def _raise(*args, **kwargs):
            raise RuntimeError("unexpected crash")

        monkeypatch.setattr("mcpvectordb.server._ingest_content", _raise)
        result = run(server.ingest_content(content="Hello world", source="test.txt"))

        assert result["status"] == "error"
        assert "Internal error" in result["error"]

    @pytest.mark.unit
    def test_library_and_metadata_forwarded(self, monkeypatch):
        """ingest_content forwards library and metadata arguments to _ingest_content."""
        from mcpvectordb import server
        from mcpvectordb.ingestor import IngestResult

        captured: dict = {}

        async def _spy(content, source, library, metadata, store):
            captured["library"] = library
            captured["metadata"] = metadata
            return IngestResult(
                status="indexed",
                doc_id="spy-doc-id",
                source=source,
                library=library,
                chunk_count=1,
            )

        monkeypatch.setattr("mcpvectordb.server._ingest_content", _spy)
        run(
            server.ingest_content(
                content="Hello world",
                source="test.txt",
                library="mylib",
                metadata={"author": "tester"},
            )
        )

        assert captured["library"] == "mylib"
        assert captured["metadata"] == {"author": "tester"}


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
        mock_emb.embed_query.return_value = np.random.rand(settings.embedding_dimension).astype(np.float32)
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
        mock_emb.embed_query.return_value = np.random.rand(settings.embedding_dimension).astype(np.float32)
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
        mock_emb.embed_query.return_value = np.random.rand(settings.embedding_dimension).astype(np.float32)
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
            embedding=[0.1] * settings.embedding_dimension,
            chunk_index=0,
            created_at=datetime.now(UTC).isoformat(),
            metadata=json.dumps({"author": "Test"}),
            file_type="pdf",
            last_modified="",
            page=0,
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


class TestOAuthProtectedResourceMetadata:
    """Tests for the /.well-known/oauth-protected-resource endpoint."""

    @pytest.fixture
    def sse_client(self, monkeypatch):
        """TestClient backed by the SSE app (includes custom routes)."""
        from mcpvectordb import server

        return TestClient(server.mcp.sse_app(), raise_server_exceptions=False)

    @pytest.mark.unit
    def test_prm_endpoint_returns_200(self, sse_client):
        """GET /.well-known/oauth-protected-resource returns 200."""
        response = sse_client.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200

    @pytest.mark.unit
    def test_prm_endpoint_returns_correct_shape(self, sse_client):
        """PRM response contains required RFC 9728 fields."""
        response = sse_client.get("/.well-known/oauth-protected-resource")
        body = response.json()

        assert "resource" in body
        assert "authorization_servers" in body
        assert "https://accounts.google.com" in body["authorization_servers"]
        assert body["bearer_methods_supported"] == ["header"]

    @pytest.mark.unit
    def test_prm_accessible_without_auth(self, sse_client, monkeypatch):
        """PRM endpoint returns 200 even when OAUTH_ENABLED=true and no Bearer token."""
        import mcpvectordb.config as config_mod

        monkeypatch.setattr(config_mod.settings, "oauth_enabled", True)
        response = sse_client.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200

    @pytest.mark.unit
    def test_prm_resource_url_uses_setting(self, sse_client, monkeypatch):
        """When OAUTH_RESOURCE_URL is set, it appears in the response."""
        import mcpvectordb.config as config_mod

        monkeypatch.setattr(
            config_mod.settings, "oauth_resource_url", "https://mcp.example.com"
        )
        response = sse_client.get("/.well-known/oauth-protected-resource")
        assert response.json()["resource"] == "https://mcp.example.com"


class TestRequireGoogleAuth:
    """Tests for the _RequireGoogleAuth ASGI middleware."""

    @pytest.mark.unit
    def test_returns_401_for_unauthenticated_request(self):
        """Unauthenticated request to a non-well-known path gets 401."""
        from mcpvectordb.server import _RequireGoogleAuth
        from starlette.applications import Starlette
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        def homepage(request: StarletteRequest):
            return PlainTextResponse("ok")

        inner_app = Starlette(routes=[Route("/mcp", homepage)])
        app = _RequireGoogleAuth(inner_app)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/mcp")
        assert response.status_code == 401

    @pytest.mark.unit
    def test_well_known_passes_without_auth(self):
        """/.well-known/* requests bypass the auth check."""
        from mcpvectordb.server import _RequireGoogleAuth
        from starlette.applications import Starlette
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        def well_known(request: StarletteRequest):
            return PlainTextResponse("metadata")

        inner_app = Starlette(
            routes=[Route("/.well-known/oauth-protected-resource", well_known)]
        )
        app = _RequireGoogleAuth(inner_app)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200

    @pytest.mark.unit
    def test_authenticated_request_passes_through(self):
        """Requests with is_authenticated=True on user are forwarded."""
        from typing import Any as TypingAny

        from mcpvectordb.server import _RequireGoogleAuth
        from starlette.applications import Starlette
        from starlette.authentication import SimpleUser
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        from starlette.types import Receive, Scope, Send

        class _AuthenticatedUser(SimpleUser):
            is_authenticated = True

        def homepage(request: StarletteRequest):
            return PlainTextResponse("ok")

        # Simulate AuthenticationMiddleware by setting scope["user"] before
        # _RequireGoogleAuth runs. Wrap: _UserSetter → _RequireGoogleAuth → Starlette
        class _UserSetter:
            def __init__(self, app: TypingAny) -> None:
                self.app = app

            async def __call__(
                self, scope: Scope, receive: Receive, send: Send
            ) -> None:
                scope["user"] = _AuthenticatedUser("tester")
                await self.app(scope, receive, send)

        inner_app = Starlette(routes=[Route("/protected", homepage)])
        app = _UserSetter(_RequireGoogleAuth(inner_app))
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/protected")
        assert response.status_code == 200


class TestValidateOAuthConfig:
    """Tests for _validate_oauth_config()."""

    @pytest.mark.unit
    def test_disabled_oauth_passes(self, monkeypatch):
        """_validate_oauth_config does nothing when OAUTH_ENABLED=false."""
        import mcpvectordb.config as config_mod
        from mcpvectordb.server import _validate_oauth_config

        monkeypatch.setattr(config_mod.settings, "oauth_enabled", False)
        _validate_oauth_config()  # should not raise

    @pytest.mark.unit
    def test_stdio_with_oauth_logs_warning(self, monkeypatch, caplog):
        """OAUTH_ENABLED=true with stdio transport logs a warning and returns."""
        import logging

        import mcpvectordb.config as config_mod
        from mcpvectordb.server import _validate_oauth_config

        monkeypatch.setattr(config_mod.settings, "oauth_enabled", True)
        monkeypatch.setattr(config_mod.settings, "mcp_transport", "stdio")

        with caplog.at_level(logging.WARNING, logger="mcpvectordb.server"):
            _validate_oauth_config()

        assert any("no effect" in r.message for r in caplog.records)

    @pytest.mark.unit
    def test_missing_client_id_raises(self, monkeypatch):
        """OAUTH_ENABLED=true without client_id raises ValueError."""
        import mcpvectordb.config as config_mod
        from mcpvectordb.server import _validate_oauth_config

        monkeypatch.setattr(config_mod.settings, "oauth_enabled", True)
        monkeypatch.setattr(config_mod.settings, "mcp_transport", "streamable-http")
        monkeypatch.setattr(config_mod.settings, "oauth_client_id", None)

        with pytest.raises(ValueError, match="OAUTH_CLIENT_ID"):
            _validate_oauth_config()

    @pytest.mark.unit
    def test_valid_oauth_config_passes(self, monkeypatch):
        """OAUTH_ENABLED=true with client_id and streamable-http passes without error."""
        import mcpvectordb.config as config_mod
        from mcpvectordb.server import _validate_oauth_config

        monkeypatch.setattr(config_mod.settings, "oauth_enabled", True)
        monkeypatch.setattr(config_mod.settings, "mcp_transport", "streamable-http")
        monkeypatch.setattr(
            config_mod.settings,
            "oauth_client_id",
            "test.apps.googleusercontent.com",
        )
        _validate_oauth_config()  # should not raise


class TestFrozenBundleContext:
    """Tests for PyInstaller frozen-bundle detection in main()."""

    @pytest.mark.unit
    def test_frozen_sets_fastembed_cache_env_var(self, tmp_path, monkeypatch):
        """When sys.frozen is True, main() sets FASTEMBED_CACHE_PATH to bundled cache."""
        import os

        import mcpvectordb.config as config_mod
        import mcpvectordb.server as server_mod

        # Simulate a PyInstaller frozen environment
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        # Ensure env var is not already set
        monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
        monkeypatch.setattr(config_mod.settings, "mcp_transport", "stdio")
        monkeypatch.setattr(server_mod.mcp, "run", MagicMock())
        monkeypatch.setattr("mcpvectordb.server.get_embedder", MagicMock())
        # lancedb_uri must be a real writable path so mkdir() succeeds
        monkeypatch.setattr(
            config_mod.settings, "lancedb_uri", str(tmp_path / "lancedb")
        )
        monkeypatch.setattr(config_mod.settings, "fastembed_cache_path", None)

        server_mod.main()

        expected = str(tmp_path / "fastembed_cache")
        assert os.environ.get("FASTEMBED_CACHE_PATH") == expected

    @pytest.mark.unit
    def test_frozen_respects_explicit_env_var(self, tmp_path, monkeypatch):
        """When FASTEMBED_CACHE_PATH is already set, frozen detection does not override it."""
        import mcpvectordb.config as config_mod
        import mcpvectordb.server as server_mod

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        explicit = str(tmp_path / "my_custom_models")
        monkeypatch.setenv("FASTEMBED_CACHE_PATH", explicit)
        monkeypatch.setattr(config_mod.settings, "mcp_transport", "stdio")
        monkeypatch.setattr(server_mod.mcp, "run", MagicMock())
        monkeypatch.setattr("mcpvectordb.server.get_embedder", MagicMock())
        monkeypatch.setattr(
            config_mod.settings, "lancedb_uri", str(tmp_path / "lancedb")
        )
        monkeypatch.setattr(config_mod.settings, "fastembed_cache_path", None)

        server_mod.main()

        import os

        assert os.environ.get("FASTEMBED_CACHE_PATH") == explicit


class TestMainFunction:
    """Tests for the main() entry point function."""

    @pytest.mark.unit
    def test_main_runs_with_stdio_transport(self, monkeypatch):
        """main() calls mcp.run(transport='stdio') when configured (lines 276-284)."""
        import mcpvectordb.config as config_mod
        import mcpvectordb.server as server_mod

        mock_run = MagicMock()
        monkeypatch.setattr(server_mod.mcp, "run", mock_run)
        monkeypatch.setattr("mcpvectordb.server.get_embedder", MagicMock())
        monkeypatch.setattr(config_mod.settings, "mcp_transport", "stdio")

        server_mod.main()

        mock_run.assert_called_once_with(transport="stdio")

    @pytest.mark.unit
    def test_main_runs_with_sse_transport(self, monkeypatch):
        """main() calls mcp.run with transport='sse' for the sse fallback branch."""
        import mcpvectordb.config as config_mod
        import mcpvectordb.server as server_mod

        mock_run = MagicMock()
        monkeypatch.setattr(server_mod.mcp, "run", mock_run)
        monkeypatch.setattr("mcpvectordb.server.get_embedder", MagicMock())
        monkeypatch.setattr(config_mod.settings, "mcp_transport", "sse")

        server_mod.main()

        mock_run.assert_called_once_with(transport="sse")


@pytest.fixture
def upload_client(monkeypatch):
    """TestClient with _ingest_content and _convert patched for upload endpoint tests."""
    from mcpvectordb import server
    from mcpvectordb.ingestor import IngestResult

    async def _fake_ingest_content(content, source, library, metadata, store):
        return IngestResult(
            status="indexed",
            doc_id="upload-doc-id",
            source=source,
            library=library,
            chunk_count=2,
        )

    monkeypatch.setattr("mcpvectordb.server._ingest_content", _fake_ingest_content)
    monkeypatch.setattr("mcpvectordb.server._convert", lambda path: "# Converted")
    return TestClient(server.mcp.sse_app(), raise_server_exceptions=False)


class TestUploadEndpoint:
    """Tests for the POST /upload HTTP endpoint."""

    @pytest.mark.unit
    def test_upload_success_returns_indexed(self, upload_client):
        """Successful upload returns 200 with status='indexed' and doc_id."""
        response = upload_client.post(
            "/upload",
            files={"file": ("test.txt", b"hello world", "text/plain")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "indexed"
        assert "doc_id" in body

    @pytest.mark.unit
    def test_upload_missing_file_field_returns_400(self, upload_client):
        """POST with no file field returns 400 with 'Missing' in the error message."""
        response = upload_client.post("/upload", data={"library": "default"})
        assert response.status_code == 400
        assert "Missing" in response.json()["error"]

    @pytest.mark.unit
    def test_upload_invalid_metadata_json_returns_400(self, upload_client):
        """POST with non-JSON metadata field returns 400 with 'metadata' in the error."""
        response = upload_client.post(
            "/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
            data={"metadata": "not-json"},
        )
        assert response.status_code == 400
        assert "metadata" in response.json()["error"]

    @pytest.mark.unit
    def test_upload_unsupported_format_returns_422(self, monkeypatch, upload_client):
        """_convert raising UnsupportedFormatError returns 422 with 'Unsupported' in error."""
        from mcpvectordb.exceptions import UnsupportedFormatError

        monkeypatch.setattr(
            "mcpvectordb.server._convert",
            lambda path: (_ for _ in ()).throw(UnsupportedFormatError(".xyz")),
        )
        response = upload_client.post(
            "/upload",
            files={"file": ("file.xyz", b"data", "application/octet-stream")},
        )
        assert response.status_code == 422
        assert "Unsupported" in response.json()["error"]

    @pytest.mark.unit
    def test_upload_library_and_metadata_forwarded(self, monkeypatch, upload_client):
        """Upload correctly forwards library and metadata to _ingest_content."""
        from mcpvectordb.ingestor import IngestResult

        captured: dict = {}

        async def _spy(content, source, library, metadata, store):
            captured["library"] = library
            captured["metadata"] = metadata
            return IngestResult(
                status="indexed",
                doc_id="spy-id",
                source=source,
                library=library,
                chunk_count=1,
            )

        monkeypatch.setattr("mcpvectordb.server._ingest_content", _spy)
        upload_client.post(
            "/upload",
            files={"file": ("report.txt", b"content", "text/plain")},
            data={"library": "research", "metadata": '{"author": "tester"}'},
        )

        assert captured["library"] == "research"
        assert captured["metadata"] == {"author": "tester"}

    @pytest.mark.unit
    def test_upload_ingestion_error_returns_500(self, monkeypatch, upload_client):
        """IngestionError from _ingest_content returns 500 with 'Ingestion failed' in error."""
        from mcpvectordb.exceptions import IngestionError

        async def _raise(*args, **kwargs):
            raise IngestionError("store unavailable")

        monkeypatch.setattr("mcpvectordb.server._ingest_content", _raise)
        response = upload_client.post(
            "/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 500
        assert "Ingestion failed" in response.json()["error"]

    @pytest.mark.unit
    def test_upload_conversion_error_returns_500(self, monkeypatch, upload_client):
        """RuntimeError from _convert returns 500 with 'Conversion failed' in error."""
        monkeypatch.setattr(
            "mcpvectordb.server._convert",
            lambda path: (_ for _ in ()).throw(RuntimeError("codec crash")),
        )
        response = upload_client.post(
            "/upload",
            files={"file": ("doc.pdf", b"%PDF", "application/pdf")},
        )
        assert response.status_code == 500
        assert "Conversion failed" in response.json()["error"]
