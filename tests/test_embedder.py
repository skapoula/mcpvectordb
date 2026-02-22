"""Tests for embedder.py — embedding shape, batch behaviour, singleton, prefixes."""

import numpy as np
import pytest

from mcpvectordb.config import settings


class TestEmbedderShape:
    """Tests for vector dimensions and types (requires real model — slow)."""

    @pytest.mark.slow
    def test_embed_documents_shape(self):
        """embed_documents returns array of shape (n, 768)."""
        from mcpvectordb.embedder import get_embedder

        emb = get_embedder()
        result = emb.embed_documents(["hello world", "test document"])
        assert result.shape == (2, 768)
        assert result.dtype == np.float32

    @pytest.mark.slow
    def test_embed_query_shape(self):
        """embed_query returns array of shape (768,)."""
        from mcpvectordb.embedder import get_embedder

        emb = get_embedder()
        result = emb.embed_query("what is the capital of France?")
        assert result.shape == (768,)
        assert result.dtype == np.float32

    @pytest.mark.slow
    def test_embed_single_document(self):
        """embed_documents with one text returns shape (1, 768)."""
        from mcpvectordb.embedder import get_embedder

        result = get_embedder().embed_documents(["single text"])
        assert result.shape == (1, 768)

    @pytest.mark.slow
    def test_embed_empty_list(self):
        """embed_documents with empty list returns empty array of correct width."""
        from mcpvectordb.embedder import get_embedder

        result = get_embedder().embed_documents([])
        assert result.shape == (0, 768)

    @pytest.mark.slow
    def test_query_and_document_embeddings_differ(self):
        """Query and document embeddings for the same text differ (different prefix)."""
        from mcpvectordb.embedder import get_embedder

        emb = get_embedder()
        text = "machine learning"
        doc_vec = emb.embed_documents([text])[0]
        qry_vec = emb.embed_query(text)
        # They should not be identical due to different prefixes
        assert not np.allclose(doc_vec, qry_vec)


class TestEmbedderSingleton:
    """Tests for singleton behaviour."""

    @pytest.mark.unit
    def test_get_embedder_returns_same_instance(self, mock_embedder):
        """get_embedder() returns the same object on repeated calls."""
        from mcpvectordb.embedder import get_embedder

        a = get_embedder()
        b = get_embedder()
        assert a is b

    @pytest.mark.unit
    def test_mock_embedder_shape(self, mock_embedder):
        """Mock embedder returns correct shape for downstream tests."""
        result = mock_embedder.embed_documents(["a", "b"])
        assert result.shape == (2, settings.embedding_dimension)

        q_result = mock_embedder.embed_query("query")
        assert q_result.shape == (settings.embedding_dimension,)


class TestEmbeddingError:
    """Tests that EmbeddingError is raised on failure."""

    @pytest.mark.unit
    def test_embed_documents_raises_on_model_failure(self, monkeypatch):
        """EmbeddingError is raised when the underlying model errors."""
        from mcpvectordb.embedder import Embedder
        from mcpvectordb.exceptions import EmbeddingError

        emb = object.__new__(Embedder)
        model_mock = pytest.importorskip("unittest.mock").MagicMock()
        model_mock.embed.side_effect = RuntimeError("GPU OOM")
        emb._model = model_mock
        emb._batch_size = 32

        with pytest.raises(EmbeddingError):
            emb.embed_documents(["text"])


class TestEmbedderUnit:
    """Unit tests for Embedder using mocked models — no real model load."""

    @pytest.mark.unit
    def test_init_loads_sentence_transformer_and_stores_batch_size(self, monkeypatch):
        """Embedder.__init__ loads TextEmbedding and stores batch_size (lines 34-38)."""
        from unittest.mock import MagicMock

        import fastembed

        from mcpvectordb.embedder import Embedder

        mock_model = MagicMock()
        mock_te_class = MagicMock(return_value=mock_model)
        monkeypatch.setattr(fastembed, "TextEmbedding", mock_te_class)

        emb = Embedder("test-model", batch_size=16)

        mock_te_class.assert_called_once_with(model_name="test-model")
        assert emb._model is mock_model
        assert emb._batch_size == 16

    @pytest.mark.unit
    def test_embed_documents_empty_list_returns_zero_shape_without_model_call(self):
        """embed_documents([]) returns (0, 768) float32 array without calling model (line 55)."""
        from unittest.mock import MagicMock

        from mcpvectordb.embedder import Embedder

        emb = object.__new__(Embedder)
        emb._model = MagicMock()
        emb._batch_size = 32

        result = emb.embed_documents([])

        assert result.shape == (0, settings.embedding_dimension)
        assert result.dtype == np.float32
        emb._model.encode.assert_not_called()

    @pytest.mark.unit
    def test_embed_documents_returns_float32_array(self):
        """embed_documents returns float32 array of shape (n, 768) on success (line 64)."""
        from unittest.mock import MagicMock

        from mcpvectordb.embedder import Embedder

        emb = object.__new__(Embedder)
        mock_model = MagicMock()
        mock_model.embed.return_value = [np.random.rand(768).astype(np.float32) for _ in range(2)]
        emb._model = mock_model
        emb._batch_size = 32

        result = emb.embed_documents(["text one", "text two"])

        assert result.shape == (2, 768)
        assert result.dtype == np.float32

    @pytest.mark.unit
    def test_embed_query_returns_float32_vector(self):
        """embed_query returns float32 array of shape (768,) on success (lines 82-89)."""
        from unittest.mock import MagicMock

        from mcpvectordb.embedder import Embedder

        emb = object.__new__(Embedder)
        mock_model = MagicMock()
        mock_model.embed.return_value = [np.random.rand(768).astype(np.float32)]
        emb._model = mock_model
        emb._batch_size = 32

        result = emb.embed_query("what is the capital?")

        assert result.shape == (768,)
        assert result.dtype == np.float32

    @pytest.mark.unit
    def test_embed_query_raises_embedding_error_on_model_failure(self):
        """embed_query raises EmbeddingError when the model raises (lines 90-91)."""
        from unittest.mock import MagicMock

        from mcpvectordb.embedder import Embedder
        from mcpvectordb.exceptions import EmbeddingError

        emb = object.__new__(Embedder)
        mock_model = MagicMock()
        mock_model.encode.side_effect = RuntimeError("GPU OOM")
        emb._model = mock_model
        emb._batch_size = 32

        with pytest.raises(EmbeddingError, match="Failed to embed query"):
            emb.embed_query("test query")

    @pytest.mark.unit
    def test_get_embedder_creates_instance_when_none(self, monkeypatch):
        """get_embedder initialises a new Embedder when _instance is None (line 98)."""
        from unittest.mock import MagicMock

        import sentence_transformers

        import mcpvectordb.embedder as embedder_mod

        monkeypatch.setattr(sentence_transformers, "SentenceTransformer", MagicMock())
        monkeypatch.setattr(embedder_mod, "_instance", None)

        result = embedder_mod.get_embedder()

        assert isinstance(result, embedder_mod.Embedder)
