"""Tests for ingestor.py — pipeline, dedup scenarios, URL mocking."""

import asyncio
import json

import numpy as np
import pytest

from mcpvectordb.exceptions import IngestionError, UnsupportedFormatError
from mcpvectordb.ingestor import BulkIngestResult, IngestResult, ingest, ingest_folder


def run(coro):
    """Run a coroutine synchronously in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def _patch_chunker(monkeypatch):
    """Patch chunker.chunk to return three synthetic chunks without tokenizing."""
    from mcpvectordb.chunker import Chunk

    texts = ["chunk one", "chunk two", "chunk three"]
    monkeypatch.setattr(
        "mcpvectordb.ingestor.chunk_with_overlap",
        lambda text: [Chunk(text=t) for t in texts] if text.strip() else [],
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

    @pytest.mark.integration
    def test_ingest_file_sets_file_type_and_last_modified(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """Chunks store file_type, a non-empty last_modified, and page 1 (1 page)."""
        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF-1.4 minimal")

        result = run(ingest(source=f, library="default", metadata=None, store=store))
        chunks = store.get_document(result.doc_id)

        assert all(c.file_type == "pdf" for c in chunks)
        assert all(c.last_modified != "" for c in chunks)
        assert all(c.page == 1 for c in chunks)

    @pytest.mark.integration
    def test_ingest_file_type_matches_extension(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """file_type is derived from the file extension, lowercased."""
        f = tmp_path / "slides.DOCX"
        f.write_bytes(b"PK fake docx content")

        result = run(ingest(source=f, library="default", metadata=None, store=store))
        chunks = store.get_document(result.doc_id)

        assert all(c.file_type == "docx" for c in chunks)


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

    @pytest.mark.integration
    def test_ingest_url_sets_file_type_url(
        self, store, mock_embedder, _patch_chunker, httpx_mock
    ):
        """URL ingestion sets file_type='url' and page=0 on every chunk."""
        httpx_mock.add_response(
            url="https://example.com/page",
            content=b"<html><body><h1>Title</h1><p>Content.</p></body></html>",
            status_code=200,
        )

        result = run(
            ingest(
                source="https://example.com/page",
                library="web",
                metadata=None,
                store=store,
            )
        )
        chunks = store.get_document(result.doc_id)

        assert all(c.file_type == "url" for c in chunks)
        assert all(c.page == 0 for c in chunks)

    @pytest.mark.integration
    def test_ingest_url_uses_last_modified_header(
        self, store, mock_embedder, _patch_chunker, httpx_mock
    ):
        """last_modified is populated from the HTTP Last-Modified response header."""
        httpx_mock.add_response(
            url="https://example.com/dated",
            content=b"<html><body><p>Content.</p></body></html>",
            status_code=200,
            headers={"Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT"},
        )

        result = run(
            ingest(
                source="https://example.com/dated",
                library="web",
                metadata=None,
                store=store,
            )
        )
        chunks = store.get_document(result.doc_id)

        assert all(c.last_modified == "Wed, 01 Jan 2025 00:00:00 GMT" for c in chunks)


@pytest.fixture
def _resolve(monkeypatch):
    """Fake DNS: map hostnames to fixed IPs for the private-address guard."""
    import socket

    table: dict[str, str] = {}

    def _fake(host, *args, **kwargs):
        if host not in table:
            raise socket.gaierror(f"unknown host {host}")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake)
    return table


@pytest.fixture
def _network_transport(monkeypatch):
    """Run as a network-exposed server (the guard is off for stdio)."""
    from mcpvectordb.config import settings

    monkeypatch.setattr(settings, "mcp_transport", "streamable-http")
    monkeypatch.setattr(settings, "allow_private_urls", False)


_HTML = b"<html><body><h1>Title</h1><p>Content.</p></body></html>"


class TestIngestPdfPages:
    """PDF chunks carry the 1-indexed page they came from."""

    @pytest.mark.integration
    def test_pdf_chunks_record_page_numbers(
        self, store, mock_embedder, _patch_chunker, sample_pdf_2pages
    ):
        """Each page is chunked separately; chunk_index stays document-wide."""
        result = run(ingest(sample_pdf_2pages, "default", None, store))
        records = store.get_document(result.doc_id)
        assert [r.page for r in records] == [1, 1, 1, 2, 2, 2]
        assert [r.chunk_index for r in records] == list(range(6))

    @pytest.mark.integration
    def test_text_without_page_breaks_has_page_zero(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """Formats without page breaks keep page=0 (not applicable)."""
        f = tmp_path / "doc.docx"
        f.write_bytes(b"fake")
        result = run(ingest(f, "default", None, store))
        assert {r.page for r in store.get_document(result.doc_id)} == {0}


class TestIngestURLPrivateAddressGuard:
    """ingest_url must not fetch internal addresses on network transports."""

    @pytest.mark.integration
    @pytest.mark.parametrize("ip", ["10.0.0.5", "127.0.0.1", "169.254.169.254"])
    def test_private_address_blocked(
        self, store, mock_embedder, _resolve, _network_transport, ip
    ):
        """URLs resolving to private/loopback/link-local IPs raise IngestionError."""
        _resolve["internal.corp"] = ip
        with pytest.raises(IngestionError, match="non-public address"):
            run(ingest("http://internal.corp/", "web", None, store))

    @pytest.mark.integration
    def test_public_address_allowed(
        self,
        store,
        mock_embedder,
        _patch_chunker,
        _resolve,
        _network_transport,
        httpx_mock,
    ):
        """A public address is fetched normally."""
        _resolve["example.com"] = "93.184.216.34"
        httpx_mock.add_response(url="https://example.com/doc", content=_HTML)
        assert run(ingest("https://example.com/doc", "web", None, store)).status == (
            "indexed"
        )

    @pytest.mark.integration
    def test_redirect_to_private_address_blocked(
        self, store, mock_embedder, _resolve, _network_transport, httpx_mock
    ):
        """A public URL redirecting to an internal host is blocked at the hop."""
        _resolve["example.com"] = "93.184.216.34"
        _resolve["internal.corp"] = "10.1.2.3"
        httpx_mock.add_response(
            url="https://example.com/r",
            status_code=302,
            headers={"Location": "http://internal.corp/secret"},
        )
        with pytest.raises(IngestionError, match="non-public address"):
            run(ingest("https://example.com/r", "web", None, store))

    @pytest.mark.integration
    def test_dns_rebinding_blocked(
        self, store, mock_embedder, _network_transport, monkeypatch
    ):
        """A host that turns private after the first lookup is never connected to."""
        import socket

        answers = iter(["93.184.216.34"])

        def _rebinding(host, *args, **kwargs):
            ip = next(answers, "127.0.0.1")
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

        monkeypatch.setattr(socket, "getaddrinfo", _rebinding)
        with pytest.raises(IngestionError, match="non-public address"):
            run(ingest("http://rebind.test:9/", "web", None, store))

    @pytest.mark.unit
    def test_pinned_backend_connects_to_checked_address(self, _resolve, monkeypatch):
        """The socket opens to the IP that passed the check, not a fresh lookup."""
        from mcpvectordb.ingestor import _PinnedBackend

        _resolve["example.com"] = "93.184.216.34"
        backend = _PinnedBackend()
        hosts = []

        async def _connect(host, port, *args, **kwargs):
            hosts.append(host)
            return "stream"

        monkeypatch.setattr(backend._inner, "connect_tcp", _connect)
        assert run(backend.connect_tcp("example.com", 443)) == "stream"
        assert hosts == ["93.184.216.34"]

    @pytest.mark.integration
    def test_stdio_allows_private_address(
        self, store, mock_embedder, _patch_chunker, _resolve, httpx_mock, monkeypatch
    ):
        """Local stdio use may ingest intranet pages."""
        from mcpvectordb.config import settings

        monkeypatch.setattr(settings, "mcp_transport", "stdio")
        _resolve["intranet"] = "10.0.0.7"
        httpx_mock.add_response(url="http://intranet/page", content=_HTML)
        assert run(ingest("http://intranet/page", "web", None, store)).status == (
            "indexed"
        )

    @pytest.mark.integration
    def test_opt_out_allows_private_address(
        self,
        store,
        mock_embedder,
        _patch_chunker,
        _resolve,
        _network_transport,
        httpx_mock,
        monkeypatch,
    ):
        """ALLOW_PRIVATE_URLS=true disables the guard."""
        from mcpvectordb.config import settings

        monkeypatch.setattr(settings, "allow_private_urls", True)
        _resolve["intranet"] = "10.0.0.7"
        httpx_mock.add_response(url="http://intranet/page", content=_HTML)
        assert run(ingest("http://intranet/page", "web", None, store)).status == (
            "indexed"
        )


class TestIngestOverlap:
    """Each stored chunk records how much of the previous chunk it repeats."""

    @pytest.mark.integration
    def test_chunk_overlap_is_stored(self, store, mock_embedder, monkeypatch):
        """The overlap the chunker reports is written to each record."""
        from mcpvectordb.chunker import Chunk
        from mcpvectordb.ingestor import ingest_content

        monkeypatch.setattr(
            "mcpvectordb.ingestor.chunk_with_overlap",
            lambda text: [Chunk(text="a b c"), Chunk(text="b c d", overlap=3)],
        )
        result = run(ingest_content("a b c d", "notes.md", "default", None, store))
        assert [r.overlap for r in store.get_document(result.doc_id)] == [0, 3]

    @pytest.mark.integration
    def test_repetitive_document_rebuilds_exactly(self, store, mock_embedder):
        """Real chunker, store and join: 1,200 repeated words come back intact."""
        from mcpvectordb.chunker import Chunk, join_chunks
        from mcpvectordb.ingestor import ingest_content

        text = " ".join(["word"] * 1200)
        result = run(ingest_content(text, "words.md", "default", None, store))
        records = store.get_document(result.doc_id)
        assert len(records) > 1
        rebuilt = join_chunks(
            [Chunk(text=r.content, overlap=r.overlap) for r in records]
        )
        assert rebuilt == text


class TestIngestDedup:
    """Deduplication scenarios — all three cases."""

    @pytest.mark.integration
    def test_ingest_waits_for_lock_held_by_another_process(
        self, store, mock_embedder, _patch_chunker
    ):
        """A second process ingesting the same source blocks this one until done."""
        from filelock import FileLock

        from mcpvectordb.ingestor import ingest_content

        def _ingest():
            return ingest_content("v1", "notes.md", "default", None, store)

        async def _attempt():
            return await asyncio.wait_for(_ingest(), timeout=0.5)

        # A separate FileLock instance takes its own OS lock, as a CLI run would.
        other = FileLock(store.source_lock_path("notes.md", "default"))
        other.acquire()
        try:
            with pytest.raises(TimeoutError):
                run(_attempt())
        finally:
            other.release()
        assert run(_attempt()).status == "indexed"

    @pytest.mark.integration
    def test_concurrent_ingests_of_one_source_leave_one_document(
        self, store, mock_embedder, _patch_chunker
    ):
        """Racing ingests of the same source must not both survive in the index."""
        from mcpvectordb.ingestor import ingest_content

        async def _race():
            return await asyncio.gather(
                ingest_content("version one", "notes.md", "default", None, store),
                ingest_content("version two", "notes.md", "default", None, store),
            )

        # Create the table first so only the dedup race is exercised.
        run(ingest_content("other", "other.md", "other", None, store))
        results = run(_race())
        docs = store.list_documents(library="default", limit=10, offset=0)
        assert len(docs) == 1
        assert sorted(r.status for r in results) == ["indexed", "replaced"]

    @pytest.mark.integration
    def test_concurrent_identical_ingests_index_once(
        self, store, mock_embedder, _patch_chunker
    ):
        """Racing ingests of one source with the same content: one indexes."""
        from mcpvectordb.ingestor import ingest_content

        async def _race():
            return await asyncio.gather(
                *(
                    ingest_content("same text", "notes.md", "default", None, store)
                    for _ in range(3)
                )
            )

        # Create the table first so only the dedup race is exercised.
        run(ingest_content("other", "other.md", "other", None, store))
        results = run(_race())
        docs = store.list_documents(library="default", limit=10, offset=0)
        assert len(docs) == 1
        assert sorted(r.status for r in results) == ["indexed", "skipped", "skipped"]

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
        """A RuntimeError from convert() is wrapped in IngestionError."""
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
        """A RuntimeError from chunk() is wrapped in IngestionError."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF content")

        def _bad_chunk(_text):
            raise RuntimeError("tokenizer crash")

        monkeypatch.setattr("mcpvectordb.ingestor.chunk_with_overlap", _bad_chunk)

        with pytest.raises(IngestionError, match="Chunking failed"):
            run(ingest(source=f, library="default", metadata=None, store=store))

    @pytest.mark.integration
    def test_empty_chunks_raises_ingestion_error(
        self, tmp_path, store, mock_embedder, _patch_converter, monkeypatch
    ):
        """Empty chunk list raises IngestionError."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF content")

        monkeypatch.setattr("mcpvectordb.ingestor.chunk_with_overlap", lambda _text: [])

        with pytest.raises(IngestionError, match="No usable chunks"):
            run(ingest(source=f, library="default", metadata=None, store=store))

    @pytest.mark.integration
    def test_embedding_error_becomes_ingestion_error(
        self, tmp_path, store, _patch_converter, _patch_chunker, monkeypatch
    ):
        """An exception from embed_documents() is wrapped in IngestionError."""
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
        """A RuntimeError from store.upsert_chunks() is wrapped in IngestionError."""
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
        """_extract_title returns the last path component when no heading is found."""
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
        """IngestionError is raised when MarkItDown fails in _convert_html_bytes."""
        from unittest.mock import MagicMock

        import markitdown

        from mcpvectordb.exceptions import IngestionError
        from mcpvectordb.ingestor import _convert_html_bytes

        monkeypatch.setattr(
            markitdown,
            "MarkItDown",
            MagicMock(side_effect=RuntimeError("conversion boom")),
        )

        with pytest.raises(IngestionError, match="HTML conversion failed"):
            run(
                _convert_html_bytes(
                    b"<html><body>test</body></html>", "https://example.com"
                )
            )


class TestIngestFolder:
    """Tests for ingest_folder() bulk ingestion."""

    @pytest.mark.integration
    async def test_ingest_folder_indexes_supported_files(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """Folder with 2 .pdf and 1 .txt → total_files=3, indexed=3, failed=0."""
        (tmp_path / "a.pdf").write_bytes(b"%PDF minimal")
        (tmp_path / "b.pdf").write_bytes(b"%PDF minimal2")
        (tmp_path / "c.txt").write_text("some text content")

        # max_concurrency=1 avoids LanceDB concurrent-write race during table init
        result = await ingest_folder(
            folder=tmp_path,
            library="default",
            metadata=None,
            store=store,
            max_concurrency=1,
        )

        assert result.total_files == 3
        assert result.indexed == 3
        assert result.failed == 0

    @pytest.mark.integration
    async def test_ingest_folder_optimizes_store_once(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """A bulk ingest ends with one compaction of the store."""
        (tmp_path / "a.pdf").write_bytes(b"%PDF minimal")
        (tmp_path / "b.pdf").write_bytes(b"%PDF minimal2")
        calls = []
        store.optimize = lambda **k: calls.append(k)

        await ingest_folder(
            folder=tmp_path,
            library="default",
            metadata=None,
            store=store,
            max_concurrency=1,
        )

        assert len(calls) == 1

    @pytest.mark.integration
    async def test_ingest_folder_skips_unsupported_extensions(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """Folder with .pdf + .xyz → only .pdf counted (total_files=1)."""
        (tmp_path / "doc.pdf").write_bytes(b"%PDF minimal")
        (tmp_path / "data.xyz").write_text("unsupported")

        result = await ingest_folder(
            folder=tmp_path, library="default", metadata=None, store=store
        )

        assert result.total_files == 1
        assert result.indexed == 1

    @pytest.mark.integration
    async def test_ingest_folder_recursive_finds_nested_files(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """docs/sub/file.pdf with recursive=True → found."""
        sub = tmp_path / "docs" / "sub"
        sub.mkdir(parents=True)
        (sub / "file.pdf").write_bytes(b"%PDF nested")

        result = await ingest_folder(
            folder=tmp_path,
            library="default",
            metadata=None,
            store=store,
            recursive=True,
        )

        assert result.total_files == 1
        assert result.indexed == 1

    @pytest.mark.integration
    async def test_ingest_folder_non_recursive_ignores_subdirs(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """docs/sub/file.pdf with recursive=False → not found."""
        sub = tmp_path / "docs" / "sub"
        sub.mkdir(parents=True)
        (sub / "file.pdf").write_bytes(b"%PDF nested")

        result = await ingest_folder(
            folder=tmp_path,
            library="default",
            metadata=None,
            store=store,
            recursive=False,
        )

        assert result.total_files == 0

    @pytest.mark.integration
    async def test_ingest_folder_one_failure_does_not_stop_batch(
        self, tmp_path, store, monkeypatch
    ):
        """One file raising yields failed=1 while the others are indexed."""
        (tmp_path / "good.pdf").write_bytes(b"%PDF good")
        (tmp_path / "bad.pdf").write_bytes(b"%PDF bad")
        (tmp_path / "also_good.txt").write_text("text content")

        async def _selective_ingest(source, library, metadata, store):
            if str(source).endswith("bad.pdf"):
                raise IngestionError("simulated failure")
            return IngestResult(
                status="indexed",
                doc_id="fake-doc-id",
                source=str(source),
                library=library,
                chunk_count=3,
            )

        monkeypatch.setattr("mcpvectordb.ingestor.ingest", _selective_ingest)

        result = await ingest_folder(
            folder=tmp_path, library="default", metadata=None, store=store
        )

        assert result.failed == 1
        assert result.indexed == 2
        assert len(result.errors) == 1
        assert "bad.pdf" in result.errors[0]["file"]

    @pytest.mark.integration
    async def test_ingest_folder_missing_folder_raises(self, tmp_path, store):
        """Non-existent path raises IngestionError."""
        with pytest.raises(IngestionError):
            await ingest_folder(
                folder=tmp_path / "does_not_exist",
                library="default",
                metadata=None,
                store=store,
            )

    @pytest.mark.integration
    async def test_ingest_folder_file_path_raises(self, tmp_path, store):
        """Passing a file path (not a dir) raises IngestionError."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF content")

        with pytest.raises(IngestionError):
            await ingest_folder(folder=f, library="default", metadata=None, store=store)

    @pytest.mark.integration
    async def test_ingest_folder_returns_bulk_ingest_result(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """Return type is BulkIngestResult."""
        (tmp_path / "doc.pdf").write_bytes(b"%PDF content")

        result = await ingest_folder(
            folder=tmp_path, library="default", metadata=None, store=store
        )

        assert isinstance(result, BulkIngestResult)

    @pytest.mark.integration
    async def test_ingest_folder_empty_folder_returns_zero_totals(
        self, tmp_path, store
    ):
        """Empty dir → total_files=0, indexed=0, failed=0."""
        result = await ingest_folder(
            folder=tmp_path, library="default", metadata=None, store=store
        )

        assert result.total_files == 0
        assert result.indexed == 0
        assert result.failed == 0

    @pytest.mark.integration
    async def test_ingest_folder_parallel_all_results_collected(
        self, tmp_path, store, monkeypatch
    ):
        """Folder with 6 files, max_concurrency=3 → all 6 in results, failed=0."""
        for i in range(6):
            (tmp_path / f"doc{i}.pdf").write_bytes(b"%PDF content")

        async def _fake_ingest(source, library, metadata, store):
            return IngestResult(
                status="indexed",
                doc_id="fake-id",
                source=str(source),
                library=library,
                chunk_count=1,
            )

        monkeypatch.setattr("mcpvectordb.ingestor.ingest", _fake_ingest)

        result = await ingest_folder(
            folder=tmp_path,
            library="default",
            metadata=None,
            store=store,
            max_concurrency=3,
        )

        assert len(result.results) == 6
        assert result.failed == 0

    @pytest.mark.unit
    async def test_ingest_folder_max_concurrency_zero_clamped_to_one(
        self, tmp_path, store, mock_embedder, _patch_chunker, _patch_converter
    ):
        """max_concurrency=0 is clamped to 1 and still returns BulkIngestResult."""
        (tmp_path / "doc.pdf").write_bytes(b"%PDF content")

        result = await ingest_folder(
            folder=tmp_path,
            library="default",
            metadata=None,
            store=store,
            max_concurrency=0,
        )

        assert isinstance(result, BulkIngestResult)
        assert result.total_files == 1
