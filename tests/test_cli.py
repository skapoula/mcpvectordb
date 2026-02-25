"""Tests for cli.py — argument parsing and integration scenarios."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from mcpvectordb.exceptions import IngestionError
from mcpvectordb.ingestor import BulkIngestResult, IngestResult


def _make_bulk_result(tmp_path, failed: int = 0, indexed: int = 1) -> BulkIngestResult:
    """Build a minimal BulkIngestResult for use in tests."""
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
def test_cli_missing_folder_arg_exits_nonzero():
    """No positional folder arg → argparse error, exit 2."""
    from mcpvectordb.cli import main

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest"]
    ):
        main()
    assert exc_info.value.code == 2


@pytest.mark.unit
def test_cli_success_exits_zero(tmp_path, monkeypatch):
    """ingest_folder returning failed=0 → exit 0."""
    import mcpvectordb.cli as cli_mod

    bulk = _make_bulk_result(tmp_path, failed=0, indexed=1)

    async def _fake_ingest_folder(**kwargs):
        return bulk

    monkeypatch.setattr(cli_mod, "get_embedder", MagicMock())
    monkeypatch.setattr(cli_mod, "_get_tokenizer", MagicMock())
    monkeypatch.setattr(cli_mod, "ingest_folder", _fake_ingest_folder)
    monkeypatch.setattr(cli_mod, "Store", MagicMock())

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest", str(tmp_path)]
    ):
        cli_mod.main()
    assert exc_info.value.code == 0


@pytest.mark.unit
def test_cli_failure_exits_one(tmp_path, monkeypatch):
    """ingest_folder returning failed=1 → exit 1."""
    import mcpvectordb.cli as cli_mod

    bulk = _make_bulk_result(tmp_path, failed=1, indexed=1)

    async def _fake_ingest_folder(**kwargs):
        return bulk

    monkeypatch.setattr(cli_mod, "get_embedder", MagicMock())
    monkeypatch.setattr(cli_mod, "_get_tokenizer", MagicMock())
    monkeypatch.setattr(cli_mod, "ingest_folder", _fake_ingest_folder)
    monkeypatch.setattr(cli_mod, "Store", MagicMock())

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest", str(tmp_path)]
    ):
        cli_mod.main()
    assert exc_info.value.code == 1


@pytest.mark.unit
def test_cli_bad_folder_exits_one(tmp_path, monkeypatch, capsys):
    """IngestionError from ingest_folder → clean error on stderr, exit 1."""
    import mcpvectordb.cli as cli_mod

    async def _raise(**kwargs):
        raise IngestionError("Folder not found")

    monkeypatch.setattr(cli_mod, "get_embedder", MagicMock())
    monkeypatch.setattr(cli_mod, "_get_tokenizer", MagicMock())
    monkeypatch.setattr(cli_mod, "ingest_folder", _raise)
    monkeypatch.setattr(cli_mod, "Store", MagicMock())

    with pytest.raises(SystemExit) as exc_info, patch(
        "sys.argv", ["mcpvectordb-ingest", "/nonexistent/path"]
    ):
        cli_mod.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "Traceback" not in captured.err
