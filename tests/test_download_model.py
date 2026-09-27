"""Tests for the mcpvectordb-download-model entry point."""

from unittest.mock import MagicMock

import pytest

from mcpvectordb import _download_model
from mcpvectordb.config import settings


@pytest.mark.unit
def test_downloads_tokenizer_the_chunker_loads(monkeypatch, tmp_path):
    """The tokenizer fetched must be the one chunker._get_tokenizer() loads."""
    monkeypatch.setattr(settings, "embedding_model", "org/some-other-model")
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path))
    monkeypatch.setattr("fastembed.TextEmbedding", MagicMock())
    auto_tokenizer = MagicMock()
    monkeypatch.setattr("transformers.AutoTokenizer", auto_tokenizer)

    _download_model.download_model()

    auto_tokenizer.from_pretrained.assert_called_once_with(
        "org/some-other-model", trust_remote_code=True
    )
