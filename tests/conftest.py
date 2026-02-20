"""Shared pytest fixtures for mcpvectordb tests."""

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from mcpvectordb.store import Store


@pytest.fixture
def lancedb_dir(tmp_path: Path) -> Path:
    """Isolated temporary LanceDB directory. Never touches the user's real database."""
    return tmp_path / "lancedb"


@pytest.fixture
def store(lancedb_dir: Path) -> Store:
    """Fresh Store instance backed by a tmp LanceDB directory."""
    return Store(uri=str(lancedb_dir), table_name="test_documents")


@pytest.fixture
def mock_embedder(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch embedder._instance with a mock returning random 768d vectors.

    Avoids loading the real 768d model in fast tests.
    """
    embedder = MagicMock()
    embedder.embed_documents.side_effect = lambda texts: np.random.rand(
        len(texts), 768
    ).astype(np.float32)
    embedder.embed_query.return_value = np.random.rand(768).astype(np.float32)
    monkeypatch.setattr("mcpvectordb.embedder._instance", embedder)
    return embedder


# ── Sample document fixtures ───────────────────────────────────────────────────
# All point to pre-committed minimal files in examples/sample_docs/.
# Paths are relative to the project root; tests are run from there via pytest.

SAMPLE_DOCS = Path(__file__).parent.parent / "examples" / "sample_docs"


@pytest.fixture
def sample_pdf() -> Path:
    """Tiny real PDF fixture."""
    return SAMPLE_DOCS / "sample.pdf"


@pytest.fixture
def sample_docx() -> Path:
    """Tiny real DOCX fixture."""
    return SAMPLE_DOCS / "sample.docx"


@pytest.fixture
def sample_pptx() -> Path:
    """Tiny real PPTX fixture."""
    return SAMPLE_DOCS / "sample.pptx"


@pytest.fixture
def sample_xlsx() -> Path:
    """Tiny real XLSX fixture."""
    return SAMPLE_DOCS / "sample.xlsx"


@pytest.fixture
def sample_html() -> Path:
    """HTML fixture."""
    return SAMPLE_DOCS / "sample.html"


@pytest.fixture
def sample_image() -> Path:
    """Small JPEG fixture."""
    return SAMPLE_DOCS / "sample.jpg"


@pytest.fixture
def sample_audio() -> Path:
    """1-second silent MP3 fixture."""
    return SAMPLE_DOCS / "sample.mp3"
