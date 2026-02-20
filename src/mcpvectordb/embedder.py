"""Sentence-transformer embedder with document/query prefix support."""

import logging

import numpy as np
from numpy.typing import NDArray

from mcpvectordb.config import settings
from mcpvectordb.exceptions import EmbeddingError

logger = logging.getLogger(__name__)

# nomic-embed-text-v1.5 uses task prefixes for asymmetric search.
_DOC_PREFIX = "search_document: "
_QUERY_PREFIX = "search_query: "

_instance: "Embedder | None" = None


class Embedder:
    """Wraps a SentenceTransformer model with document and query prefixes.

    Uses nomic-embed-text-v1.5 (768d) by default. The model is loaded once
    on first instantiation and shared across all calls.
    """

    def __init__(self, model_name: str, batch_size: int) -> None:
        """Load the sentence-transformer model.

        Args:
            model_name: HuggingFace model ID (e.g. nomic-ai/nomic-embed-text-v1.5).
            batch_size: Number of texts encoded in one forward pass.
        """
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model %s", model_name)
        self._model = SentenceTransformer(model_name, trust_remote_code=True)
        self._batch_size = batch_size

    def embed_documents(self, texts: list[str]) -> NDArray[np.float32]:
        """Embed a list of document texts.

        Prepends the 'search_document:' prefix required by nomic-embed-text-v1.5.

        Args:
            texts: List of document chunk strings to embed.

        Returns:
            Float32 array of shape (len(texts), 768).

        Raises:
            EmbeddingError: If the model fails to produce embeddings.
        """
        if not texts:
            return np.empty((0, 768), dtype=np.float32)
        try:
            prefixed = [_DOC_PREFIX + t for t in texts]
            vecs = self._model.encode(
                prefixed,
                batch_size=self._batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return np.array(vecs, dtype=np.float32)
        except Exception as e:
            raise EmbeddingError(f"Failed to embed {len(texts)} documents") from e

    def embed_query(self, query: str) -> NDArray[np.float32]:
        """Embed a single query string.

        Prepends the 'search_query:' prefix required by nomic-embed-text-v1.5.

        Args:
            query: Natural-language search query.

        Returns:
            Float32 array of shape (768,).

        Raises:
            EmbeddingError: If the model fails to produce an embedding.
        """
        try:
            prefixed = _QUERY_PREFIX + query
            vec = self._model.encode(
                prefixed,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return np.array(vec, dtype=np.float32)
        except Exception as e:
            raise EmbeddingError(f"Failed to embed query: {query!r}") from e


def get_embedder() -> "Embedder":
    """Return the module-level Embedder singleton, initialising on first call."""
    global _instance  # noqa: PLW0603
    if _instance is None:
        _instance = Embedder(
            model_name=settings.embedding_model,
            batch_size=settings.embedding_batch_size,
        )
    return _instance
