---
# No paths: field — applies to all files in mcpvectordb
---

# Testing — mcpvectordb

## Runner & Commands

- Test runner: **pytest** via `uv run pytest`.
- Default run excludes `slow` tests: `uv run pytest` (configured in `pyproject.toml`).
- Single file: `uv run pytest tests/test_converter.py -v`
- By marker: `uv run pytest -m integration -v`
- With coverage: `uv run pytest --cov=src/mcpvectordb --cov-report=term-missing`

## Pytest Markers

Declare all markers in `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
[tool.pytest.ini_options]
addopts = "-m 'not slow'"
markers = [
    "slow: audio transcription, image OCR, large file tests (deselected by default)",
    "integration: writes to a real (tmp) LanceDB on disk",
    "unit: pure function tests — no I/O, no filesystem, no network",
]
```

| Marker | When to use | Run with |
|--------|-------------|----------|
| `slow` | Audio transcription, image OCR, files > 1 MB | `uv run pytest -m slow` |
| `integration` | Any test that opens a real LanceDB table | `uv run pytest -m integration` |
| `unit` | Pure functions with no side effects | `uv run pytest -m unit` |

Tag every test with at least one marker. Untagged tests are treated as `unit`.

## Test Structure

```
tests/
├── conftest.py          # All shared fixtures live here
├── test_converter.py    # One test class per supported file type
├── test_chunker.py      # Chunking logic, edge cases, token counts
├── test_embedder.py     # Embedding shape, batch behaviour, model loading
├── test_store.py        # LanceDB read/write/delete, schema validation
└── test_server.py       # MCP tool contracts, input validation, error responses
```

## Fixtures (conftest.py)

Always define reusable fixtures in `conftest.py`, never inline in test files.

```python
# Required fixtures — implement these before writing any other tests

@pytest.fixture
def lancedb_dir(tmp_path) -> Path:
    """Isolated temporary LanceDB directory. Never touches the user's real database."""
    return tmp_path / "lancedb"

@pytest.fixture
def store(lancedb_dir) -> Store:
    """Fresh Store instance backed by tmp LanceDB."""
    return Store(uri=str(lancedb_dir), table_name="test_documents")

@pytest.fixture
def sample_pdf() -> Path:
    """Tiny real PDF from examples/sample_docs/."""
    return Path("examples/sample_docs/sample.pdf")

# One fixture per supported format: sample_docx, sample_pptx,
# sample_xlsx, sample_html, sample_image, sample_audio
```

- Always use `tmp_path` (pytest built-in) for any test that writes to disk.
- Never reference `~/.mcpvectordb/` or any user-level path in tests.
- Sample fixture files in `examples/sample_docs/` must be tiny (< 50 KB each).
  Their purpose is format coverage, not content fidelity.

## Converter Tests (test_converter.py)

One test per supported format, plus error cases:

```python
class TestPDFConverter:
    def test_converts_to_markdown(self, sample_pdf):
        result = convert(sample_pdf)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_markdown_string(self, sample_pdf):
        result = convert(sample_pdf)
        assert result.strip().startswith("#") or len(result) > 10  # non-empty markdown

class TestUnsupportedFormat:
    def test_raises_unsupported_format_error(self, tmp_path):
        bad_file = tmp_path / "file.xyz"
        bad_file.write_text("content")
        with pytest.raises(UnsupportedFormatError, match=r"\.xyz"):
            convert(bad_file)
```

- Mark audio and image tests with `@pytest.mark.slow`.
- Do not test MarkItDown internals — test that `convert()` returns non-empty Markdown.

## URL Tests (test_converter.py or test_ingestor.py)

- **Always mock `httpx`** — no real network calls in the test suite.
- Use `pytest-httpx` or `unittest.mock.patch` to return a fixture HTML response.
- Test: successful fetch → Markdown output, timeout → `IngestionError`,
  non-200 status → `IngestionError`.

```python
def test_url_ingestion(httpx_mock):
    httpx_mock.add_response(
        url="https://example.com/doc",
        text="<html><body><h1>Title</h1><p>Content</p></body></html>",
    )
    result = convert_url("https://example.com/doc")
    assert "Title" in result
```

## Store Tests (test_store.py)

- Tag all store tests with `@pytest.mark.integration`.
- Use the `store` fixture (tmp LanceDB) — never the user's real database.
- Test the full lifecycle: insert → search → get → delete.
- Test that schema violations raise `StoreError`, not LanceDB internals.
- Test that searching an empty table returns `[]`, not an exception.

## MCP Tool Tests (test_server.py)

- Test each tool's input validation: missing required fields, wrong types,
  out-of-range values should all return structured MCP error responses.
- Test that tools return the correct schema shape on success.
- Do not test the MCP transport layer (stdio/SSE) — test the tool handler functions
  directly.
- Test that `ingest_file` with an unsupported format returns an error response,
  not an unhandled exception.

## Coverage

- Minimum coverage: **80%** lines and branches across `src/mcpvectordb/`.
- Check with: `uv run pytest --cov=src/mcpvectordb --cov-fail-under=80`
- Gaps that are acceptable: third-party library call sites already covered by
  fixture tests, and `if __name__ == "__main__"` guards.
- Do not delete or weaken tests to hit coverage targets. Fix the code.

## What Not To Do

- Never use `test.only`, `pytest.mark.skip`, or `@unittest.skip` in committed code
  without a comment explaining when it will be re-enabled.
- Never assert on log output as the primary test of behaviour — test the return value
  or side effect instead.
- Never write a test that passes by catching the wrong exception type.
- Never share mutable state between tests — each test must be fully independent.
- It is unacceptable to delete or weaken tests to make the suite pass. Fix the code.
