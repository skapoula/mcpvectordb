"""Tests for cli.py — argument parsing and all three ingestion modes."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from mcpvectordb.exceptions import IngestionError
from mcpvectordb.ingestor import BulkIngestResult, IngestResult


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_ingest_result(tmp_path, status: str = "indexed") -> IngestResult:
    """Build a minimal IngestResult for single-file tests."""
    return IngestResult(
        status=status,
        doc_id="test-doc-id",
        source=str(tmp_path / "doc.pdf"),
        library="default",
        chunk_count=3,
    )


def _make_bulk_result(tmp_path, failed: int = 0, indexed: int = 1) -> BulkIngestResult:
    """Build a minimal BulkIngestResult for folder tests."""
    results = []
    if indexed:
        results.append(
            IngestResult(
                status="indexed",
                doc_id="test-doc-id",
                source=str(tmp_path / "doc.pdf"),
                library="default",
                chunk_count=3,
            )
        )
    errors = (
        [{"file": str(tmp_path / "bad.pdf"), "error": "parse error"}] if failed else []
    )
    return BulkIngestResult(
        folder=str(tmp_path),
        library="default",
        total_files=indexed + failed,
        indexed=indexed,
        replaced=0,
        skipped=0,
        failed=failed,
        results=results,
        errors=errors,
    )


@pytest.fixture(autouse=True)
def _patch_asyncio_run(monkeypatch):
    """Replace asyncio.run() with run_until_complete() to preserve event loop.

    asyncio.run() closes the event loop on completion, which breaks subsequent
    tests that call asyncio.get_event_loop().run_until_complete(). This fixture
    prevents that by reusing the existing event loop instead.
    """
    loop = asyncio.get_event_loop()
    monkeypatch.setattr("asyncio.run", loop.run_until_complete)


@pytest.fixture()
def _mock_models(monkeypatch):
    """Suppress model loading in all CLI tests."""
    import mcpvectordb.cli as cli_mod

    monkeypatch.setattr(cli_mod, "get_embedder", MagicMock())
    monkeypatch.setattr(cli_mod, "_get_tokenizer", MagicMock())
    monkeypatch.setattr(cli_mod, "Store", MagicMock())


# ── Argument parsing ───────────────────────────────────────────────────────────

@pytest.mark.unit
def test_cli_help_exits_cleanly():
    """--help prints usage and exits 0."""
    from mcpvectordb.cli import main

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest", "--help"]
    ):
        main()
    assert exc_info.value.code == 0


@pytest.mark.unit
def test_cli_missing_path_arg_exits_nonzero():
    """No positional path arg → argparse error, exit 2."""
    from mcpvectordb.cli import main

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest"]
    ):
        main()
    assert exc_info.value.code == 2


# ── (a) Single file ────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_cli_single_file_success_exits_zero(tmp_path, monkeypatch, _mock_models):
    """Single existing file → ingest() called, exit 0."""
    import mcpvectordb.cli as cli_mod

    doc = tmp_path / "doc.pdf"
    doc.write_bytes(b"%PDF")
    fake_result = _make_ingest_result(tmp_path, status="indexed")

    async def _fake_ingest(**kwargs):
        return fake_result

    monkeypatch.setattr(cli_mod, "ingest", _fake_ingest)

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest", str(doc)]
    ):
        cli_mod.main()
    assert exc_info.value.code == 0


@pytest.mark.unit
def test_cli_single_file_ingest_error_exits_one(tmp_path, monkeypatch, _mock_models, capsys):
    """ingest() raising IngestionError → clean message on stderr, exit 1."""
    import mcpvectordb.cli as cli_mod

    doc = tmp_path / "doc.pdf"
    doc.write_bytes(b"%PDF")

    async def _raise(**kwargs):
        raise IngestionError("Conversion failed")

    monkeypatch.setattr(cli_mod, "ingest", _raise)

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest", str(doc)]
    ):
        cli_mod.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "ERROR" in captured.err
    assert "Traceback" not in captured.err


# ── (b) Multiple files ────────────────────────────────────────────────────────

@pytest.mark.unit
def test_cli_multiple_files_all_succeed_exits_zero(tmp_path, monkeypatch, _mock_models):
    """Two existing files → ingest() called twice, exit 0."""
    import mcpvectordb.cli as cli_mod

    file_a = tmp_path / "a.pdf"
    file_b = tmp_path / "b.docx"
    file_a.write_bytes(b"%PDF")
    file_b.write_bytes(b"PK")

    call_count = {"n": 0}

    async def _fake_ingest(source, **kwargs):
        call_count["n"] += 1
        return IngestResult(
            status="indexed",
            doc_id=f"doc-{call_count['n']}",
            source=str(source),
            library="default",
            chunk_count=2,
        )

    monkeypatch.setattr(cli_mod, "ingest", _fake_ingest)

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest", str(file_a), str(file_b)]
    ):
        cli_mod.main()

    assert exc_info.value.code == 0
    assert call_count["n"] == 2


@pytest.mark.unit
def test_cli_multiple_files_partial_failure_exits_one(tmp_path, monkeypatch, _mock_models):
    """Two files, one fails → exit 1."""
    import mcpvectordb.cli as cli_mod

    file_a = tmp_path / "a.pdf"
    file_b = tmp_path / "b.docx"
    file_a.write_bytes(b"%PDF")
    file_b.write_bytes(b"PK")
    paths = {str(file_a), str(file_b)}
    call_count = {"n": 0}

    async def _fake_ingest(source, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise IngestionError("bad file")
        return IngestResult(
            status="indexed", doc_id="d1", source=str(source), library="default", chunk_count=1
        )

    monkeypatch.setattr(cli_mod, "ingest", _fake_ingest)

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest", str(file_a), str(file_b)]
    ):
        cli_mod.main()

    assert exc_info.value.code == 1


# ── (c) Folder ────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_cli_folder_success_exits_zero(tmp_path, monkeypatch, _mock_models):
    """Folder with no failures → ingest_folder called, exit 0."""
    import mcpvectordb.cli as cli_mod

    bulk = _make_bulk_result(tmp_path, failed=0, indexed=1)

    async def _fake_ingest_folder(**kwargs):
        return bulk

    monkeypatch.setattr(cli_mod, "ingest_folder", _fake_ingest_folder)

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest", str(tmp_path)]
    ):
        cli_mod.main()
    assert exc_info.value.code == 0


@pytest.mark.unit
def test_cli_folder_with_failures_exits_one(tmp_path, monkeypatch, _mock_models):
    """Folder with failed=1 → exit 1."""
    import mcpvectordb.cli as cli_mod

    bulk = _make_bulk_result(tmp_path, failed=1, indexed=1)

    async def _fake_ingest_folder(**kwargs):
        return bulk

    monkeypatch.setattr(cli_mod, "ingest_folder", _fake_ingest_folder)

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest", str(tmp_path)]
    ):
        cli_mod.main()
    assert exc_info.value.code == 1


@pytest.mark.unit
def test_cli_nonexistent_path_exits_one(tmp_path, monkeypatch, _mock_models, capsys):
    """Path that doesn't exist → 'Error:' on stderr, exit 1."""
    import mcpvectordb.cli as cli_mod

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest", "/nonexistent/path"]
    ):
        cli_mod.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.unit
def test_cli_folder_ingest_error_exits_one(tmp_path, monkeypatch, _mock_models, capsys):
    """IngestionError from ingest_folder → clean error on stderr, exit 1."""
    import mcpvectordb.cli as cli_mod

    async def _raise(**kwargs):
        raise IngestionError("Folder not found")

    monkeypatch.setattr(cli_mod, "ingest_folder", _raise)

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest", str(tmp_path)]
    ):
        cli_mod.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "Traceback" not in captured.err


# ── Mixed paths ───────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_cli_mixed_file_and_folder_success(tmp_path, monkeypatch, _mock_models):
    """One file + one folder, both succeed → exit 0."""
    import mcpvectordb.cli as cli_mod

    doc = tmp_path / "standalone.pdf"
    doc.write_bytes(b"%PDF")
    subdir = tmp_path / "subdir"
    subdir.mkdir()

    bulk = _make_bulk_result(subdir, failed=0, indexed=2)

    async def _fake_ingest(**kwargs):
        return _make_ingest_result(tmp_path, status="indexed")

    async def _fake_ingest_folder(**kwargs):
        return bulk

    monkeypatch.setattr(cli_mod, "ingest", _fake_ingest)
    monkeypatch.setattr(cli_mod, "ingest_folder", _fake_ingest_folder)

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest", str(doc), str(subdir)]
    ):
        cli_mod.main()

    assert exc_info.value.code == 0
