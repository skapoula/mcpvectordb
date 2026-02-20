"""Tests for ingestor.py — pipeline, dedup scenarios, URL mocking."""

import asyncio
import json

import numpy as np
import pytest

from mcpvectordb.exceptions import IngestionError, UnsupportedFormatError
from mcpvectordb.ingestor import IngestResult, ingest


def run(coro):
    """Run a coroutine synchronously in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def _patch_chunker(monkeypatch):
    """Patch chunker.chunk to return three synthetic chunks without tokenizing."""
    monkeypatch.setattr(
        "mcpvectordb.ingestor.chunk",
        lambda text: ["chunk one", "chunk two", "chunk three"] if text.strip() else [],
    )


@pytest.fixture
def _patch_converter(monkeypatch):
    """Patch converter.convert to return synthetic Markdown."""
    monkeypatch.setattr(
        "mcpvectordb.ingestor.convert",
        lambda path: "# Title\n\nSome content about the document.",
    )


class TestIngestFile:
    """Tests for local file ingestion."""

    @pytest.mark.integration
    def test_ingest_new_file(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """Ingesting a new file returns status='indexed'."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 minimal")

        result = run(ingest(source=f, library="default", metadata=None, store=store))

        assert isinstance(result, IngestResult)
        assert result.status == "indexed"
        assert result.chunk_count == 3
        assert result.library == "default"
        assert result.source == str(f)

    @pytest.mark.integration
    def test_ingest_creates_chunks_in_store(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """After ingestion the store contains the correct number of chunks."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 minimal")

        result = run(ingest(source=f, library="default", metadata=None, store=store))
        chunks = store.get_document(result.doc_id)
        assert len(chunks) == 3

    @pytest.mark.integration
    def test_ingest_stores_metadata(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """User-supplied metadata is preserved on every chunk."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 minimal")
        meta = {"author": "Alice", "year": "2025"}

        result = run(ingest(source=f, library="default", metadata=meta, store=store))
        chunks = store.get_document(result.doc_id)
        for c in chunks:
            assert json.loads(c.metadata) == meta

    @pytest.mark.integration
    def test_ingest_unsupported_format_raises(self, tmp_path, store, mock_embedder):
        """Unsupported file extension propagates UnsupportedFormatError."""
        f = tmp_path / "data.xyz"
        f.write_text("content")

        with pytest.raises(UnsupportedFormatError):
            run(ingest(source=f, library="default", metadata=None, store=store))

    @pytest.mark.integration
    def test_ingest_missing_file_raises(self, tmp_path, store, mock_embedder):
        """Ingest of a non-existent file raises IngestionError."""
        missing = tmp_path / "ghost.pdf"
        with pytest.raises(IngestionError):
            run(ingest(source=missing, library="default", metadata=None, store=store))


class TestIngestURL:
    """Tests for URL ingestion with mocked httpx."""

    @pytest.mark.integration
    def test_ingest_url_success(self, store, mock_embedder, _patch_chunker, httpx_mock):
        """URL ingestion with a mocked 200 response returns status='indexed'."""
        httpx_mock.add_response(
            url="https://example.com/doc",
            content=b"<html><body><h1>Title</h1><p>Content.</p></body></html>",
            status_code=200,
        )

        result = run(
            ingest(
                source="https://example.com/doc",
                library="web",
                metadata=None,
                store=store,
            )
        )
        assert result.status == "indexed"
        assert result.library == "web"

    @pytest.mark.integration
    def test_ingest_url_404_raises(self, store, mock_embedder, httpx_mock):
        """A 404 response raises IngestionError."""
        httpx_mock.add_response(
            url="https://example.com/missing",
            status_code=404,
        )

        with pytest.raises(IngestionError, match="404"):
            run(
                ingest(
                    source="https://example.com/missing",
                    library="web",
                    metadata=None,
                    store=store,
                )
            )

    @pytest.mark.integration
    def test_ingest_url_timeout_raises(self, store, mock_embedder, httpx_mock):
        """A network timeout raises IngestionError."""
        import httpx

        httpx_mock.add_exception(
            httpx.ReadTimeout("timeout"),
            url="https://example.com/slow",
        )

        with pytest.raises(IngestionError):
            run(
                ingest(
                    source="https://example.com/slow",
                    library="web",
                    metadata=None,
                    store=store,
                )
            )


class TestIngestDedup:
    """Deduplication scenarios — all three cases."""

    @pytest.mark.integration
    def test_dedup_same_hash_returns_skipped(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """Scenario 1: same (source, library) + same content → status='skipped'."""
        f = tmp_path / "doc.pdf"
        content = b"%PDF-1.4 constant"
        f.write_bytes(content)

        # First ingest
        r1 = run(ingest(source=f, library="default", metadata=None, store=store))
        assert r1.status == "indexed"
        initial_doc_id = r1.doc_id

        # Second ingest — same bytes
        r2 = run(ingest(source=f, library="default", metadata=None, store=store))
        assert r2.status == "skipped"
        assert r2.chunk_count == 0

        # Store still has original chunks
        assert len(store.get_document(initial_doc_id)) == 3

    @pytest.mark.integration
    def test_dedup_different_hash_returns_replaced(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """Scenario 2: same (source, library) + different content → 'replaced'."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 version_one")

        r1 = run(ingest(source=f, library="default", metadata=None, store=store))
        old_doc_id = r1.doc_id
        assert r1.status == "indexed"

        # Overwrite file with different content
        f.write_bytes(b"%PDF-1.4 version_two_completely_different")

        r2 = run(ingest(source=f, library="default", metadata=None, store=store))
        assert r2.status == "replaced"
        # Old chunks gone
        assert store.get_document(old_doc_id) == []
        # New chunks present
        assert len(store.get_document(r2.doc_id)) == 3

    @pytest.mark.integration
    def test_dedup_same_source_different_library_independent(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """Scenario 3: same source, different libraries are indexed independently."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 shared_content")

        r_a = run(ingest(source=f, library="lib_a", metadata=None, store=store))
        r_b = run(ingest(source=f, library="lib_b", metadata=None, store=store))

        assert r_a.status == "indexed"
        assert r_b.status == "indexed"
        assert r_a.doc_id != r_b.doc_id

        # Each library has its own chunks
        assert len(store.get_document(r_a.doc_id)) == 3
        assert len(store.get_document(r_b.doc_id)) == 3

        # Deleting from lib_a doesn't affect lib_b
        store.delete_document(r_a.doc_id)
        assert store.get_document(r_a.doc_id) == []
        assert len(store.get_document(r_b.doc_id)) == 3


class TestIngestFileErrorPaths:
    """Tests for exception handling in the ingest() pipeline."""

    @pytest.mark.integration
    def test_conversion_general_error_becomes_ingestion_error(
        self, tmp_path, store, mock_embedder, monkeypatch
    ):
        """A RuntimeError from convert() is wrapped in IngestionError (lines 108-109)."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF content")

        def _bad_convert(_path):
            raise RuntimeError("parse error")

        monkeypatch.setattr("mcpvectordb.ingestor.convert", _bad_convert)

        with pytest.raises(IngestionError, match="Conversion failed"):
            run(ingest(source=f, library="default", metadata=None, store=store))

    @pytest.mark.integration
    def test_chunker_error_becomes_ingestion_error(
        self, tmp_path, store, mock_embedder, _patch_converter, monkeypatch
    ):
        """A RuntimeError from chunk() is wrapped in IngestionError (lines 116-117)."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF content")

        def _bad_chunk(_text):
            raise RuntimeError("tokenizer crash")

        monkeypatch.setattr("mcpvectordb.ingestor.chunk", _bad_chunk)

        with pytest.raises(IngestionError, match="Chunking failed"):
            run(ingest(source=f, library="default", metadata=None, store=store))

    @pytest.mark.integration
    def test_empty_chunks_raises_ingestion_error(
        self, tmp_path, store, mock_embedder, _patch_converter, monkeypatch
    ):
        """Empty chunk list raises IngestionError (line 120)."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF content")

        monkeypatch.setattr("mcpvectordb.ingestor.chunk", lambda _text: [])

        with pytest.raises(IngestionError, match="No usable chunks"):
            run(ingest(source=f, library="default", metadata=None, store=store))

    @pytest.mark.integration
    def test_embedding_error_becomes_ingestion_error(
        self, tmp_path, store, _patch_converter, _patch_chunker, monkeypatch
    ):
        """An exception from embed_documents() is wrapped in IngestionError (lines 125-126)."""
        from unittest.mock import MagicMock

        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF content")

        bad_embedder = MagicMock()
        bad_embedder.embed_documents.side_effect = RuntimeError("OOM")
        monkeypatch.setattr("mcpvectordb.embedder._instance", bad_embedder)

        with pytest.raises(IngestionError, match="Embedding failed"):
            run(ingest(source=f, library="default", metadata=None, store=store))

    @pytest.mark.unit
    def test_store_write_error_becomes_ingestion_error(
        self, tmp_path, _patch_converter, _patch_chunker, monkeypatch
    ):
        """A RuntimeError from store.upsert_chunks() is wrapped in IngestionError (lines 151-152)."""
        from unittest.mock import MagicMock

        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF content")

        bad_store = MagicMock()
        bad_store.find_existing.return_value = (None, None)
        bad_store.upsert_chunks.side_effect = RuntimeError("disk full")

        mock_emb = MagicMock()
        mock_emb.embed_documents.return_value = np.zeros((3, 768), dtype=np.float32)
        monkeypatch.setattr("mcpvectordb.embedder._instance", mock_emb)

        with pytest.raises(IngestionError, match="Store write failed"):
            run(ingest(source=f, library="default", metadata=None, store=bad_store))


class TestIngestHelpers:
    """Tests for ingestor helper functions."""

    @pytest.mark.unit
    def test_extract_title_returns_first_heading(self):
        """_extract_title returns the first H1 heading content from Markdown."""
        from mcpvectordb.ingestor import _extract_title

        result = _extract_title("# My Document Title\n\nSome content.", "file.pdf")
        assert result == "My Document Title"

    @pytest.mark.unit
    def test_extract_title_falls_back_to_source_filename(self):
        """_extract_title returns the last path component when no heading is found (line 250)."""
        from mcpvectordb.ingestor import _extract_title

        result = _extract_title(
            "No heading here, just plain text.",
            "https://example.com/docs/guide.html",
        )
        assert result == "guide.html"

    @pytest.mark.integration
    def test_convert_html_bytes_raises_ingestion_error_on_markitdown_failure(
        self, monkeypatch
    ):
        """IngestionError is raised when MarkItDown fails in _convert_html_bytes (lines 231-232)."""
        import markitdown
        from unittest.mock import MagicMock
        from mcpvectordb.exceptions import IngestionError
        from mcpvectordb.ingestor import _convert_html_bytes

        monkeypatch.setattr(
            markitdown,
            "MarkItDown",
            MagicMock(side_effect=RuntimeError("conversion boom")),
        )

        with pytest.raises(IngestionError, match="HTML conversion failed"):
            run(_convert_html_bytes(b"<html><body>test</body></html>", "https://example.com"))
