# Testing — mcpvectordb
# Extends /workspace/.claude/rules/master-testing.md (loaded automatically).
# Only project-specific additions and overrides are listed here.

## Commands

```bash
uv run pytest                                              # default (excludes slow)
uv run pytest tests/test_converter.py -v                  # single file
uv run pytest -m integration -v                           # by marker
uv run pytest --cov=src/mcpvectordb --cov-report=term-missing
uv run pytest --cov=src/mcpvectordb --cov-fail-under=80   # CI gate
```

## Coverage

Minimum **80%** lines and branches across `src/mcpvectordb/`.
Acceptable gaps: third-party call sites covered by fixture tests; `if __name__ == "__main__"` guards.

## Marker Configuration

```toml
[tool.pytest.ini_options]
addopts = "-m 'not slow'"
markers = [
    "slow: audio transcription, image OCR, large file tests (deselected by default)",
    "integration: writes to a real (tmp) LanceDB on disk",
    "unit: pure function tests — no I/O, no filesystem, no network",
]
```

## Fixtures

- Use the `store` fixture (tmp LanceDB via `tmp_path`) — never the user's real database.
- One sample fixture file per supported format in `examples/sample_docs/` — keep them under 50 KB each.
- Never reference `~/.mcpvectordb/` or any user-level path in tests.

## HTTP / URL Tests

- **Always mock `httpx`** — use `pytest-httpx` or `unittest.mock.patch`.
- Test: successful fetch → Markdown, timeout → `IngestionError`, non-200 → `IngestionError`.

## MCP Tool Tests

- Test input validation: missing fields, wrong types, out-of-range values → structured error response.
- Do not test the transport layer (stdio/SSE) — test tool handler functions directly.
- Mark audio and image tests `@pytest.mark.slow`.
