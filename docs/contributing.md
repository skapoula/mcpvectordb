# Contributing to mcpvectordb

## Prerequisites

- Python 3.11 or later
- [`uv`](https://docs.astral.sh/uv/) 0.4 or later
- Git

## Local Setup

1. Fork and clone the repository:

```bash
git clone <your-fork-url> mcpvectordb
cd mcpvectordb
```

2. Install all dependencies (including dev tools):

```bash
uv sync
```

3. Copy the example config:

```bash
cp .env.example .env
```

4. Run the test suite to confirm everything works:

```bash
uv run pytest
```

All tests should pass before you start making changes.

## Running Tests

```bash
# Default: all tests except slow (audio/OCR)
uv run pytest

# Single file
uv run pytest tests/test_store.py -v

# By marker
uv run pytest -m unit -v
uv run pytest -m integration -v
uv run pytest -m slow -v

# With coverage report
uv run pytest --cov=src/mcpvectordb --cov-report=term-missing

# Enforce 80% coverage minimum
uv run pytest --cov=src/mcpvectordb --cov-fail-under=80
```

## Project Structure

```
mcpvectordb/
├── src/mcpvectordb/
│   ├── server.py       # MCP entry point; tool registrations
│   ├── config.py       # pydantic-settings; all env vars
│   ├── ingestor.py     # file/URL → Markdown → LanceDB pipeline
│   ├── converter.py    # MarkItDown wrapper; format dispatch
│   ├── chunker.py      # Token-aware recursive text splitter
│   ├── embedder.py     # sentence-transformers wrapper
│   ├── store.py        # LanceDB read/write; schema
│   └── exceptions.py   # Domain exception classes
├── tests/              # pytest suite; mirrors src/ structure
├── docs/               # User-facing documentation
├── examples/           # Sample fixture files (one per format)
└── deploy/k3s/         # Kubernetes manifests for SSE hosting
```

## Making Changes

1. Create a feature branch from `master`:

```bash
git checkout -b feat/your-feature-name
```

2. Make your changes. Run linting and type checks before committing:

```bash
uv run ruff check . && uv run ruff format .
uv run mypy src/
uv run bandit -r src/
```

3. Run the full test suite and confirm it is green:

```bash
uv run pytest
```

4. Never delete or weaken a test to make the suite pass — fix the code instead.

## Submitting a Pull Request

1. Push your branch to your fork.
2. Open a PR against `master`.
3. Describe what changed and why, not only what.
4. All CI checks must pass before review.

## Code Standards

These are enforced by the tools above — violations will fail CI.

- Line length: 88 characters (ruff, Black-compatible)
- Ruff rules: `E`, `F`, `I`, `N`, `UP`, `B`, `SIM`
- Type hints required on all public function signatures
- `pathlib.Path` for all filesystem operations — never `os.path`
- `logging` module only — no `print()` anywhere in `src/`
- Custom exceptions in `exceptions.py` — never raise raw `Exception`
- Pydantic models for all data crossing module boundaries
- In stdio mode, nothing may write to stdout except the MCP protocol frames
