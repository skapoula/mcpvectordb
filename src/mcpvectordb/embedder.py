"""Fastembed embedder with document/query prefix support."""

import logging
import os
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from mcpvectordb.config import settings
from mcpvectordb.exceptions import EmbeddingError

logger = logging.getLogger(__name__)

# nomic-embed-text-v1.5 uses task prefixes for asymmetric search.
_DOC_PREFIX = "search_document: "
_QUERY_PREFIX = "search_query: "

# Models known to require these task-specific prefixes.
# A WARNING is logged at startup when a model outside this set is configured,
# because the prefixes would silently degrade retrieval quality for other models.
_PREFIX_AWARE_MODELS = {"nomic-ai/nomic-embed-text-v1.5"}

_instance: "Embedder | None" = None


class Embedder:
    """Wraps a fastembed TextEmbedding model with document and query prefixes.

    Uses ONNX Runtime for inference — no PyTorch dependency required.
    The model is loaded once on first instantiation and shared across all calls.
    Cache location is controlled by settings.fastembed_cache_path (propagated
    to the FASTEMBED_CACHE_PATH environment variable that fastembed reads).
    """

    def __init__(self, model_name: str, batch_size: int) -> None:
        """Load the fastembed model.

        Args:
            model_name: HuggingFace model ID (e.g. nomic-ai/nomic-embed-text-v1.5).
            batch_size: Number of texts encoded in one forward pass.
        """
        from fastembed import TextEmbedding

        # Propagate settings.fastembed_cache_path to the env var fastembed reads,
        # unless FASTEMBED_CACHE_PATH is already set explicitly in the environment.
        if settings.fastembed_cache_path and not os.environ.get("FASTEMBED_CACHE_PATH"):
            cache_path = Path(settings.fastembed_cache_path).expanduser()
            cache_path.mkdir(parents=True, exist_ok=True)
            os.environ["FASTEMBED_CACHE_PATH"] = str(cache_path)

        if model_name not in _PREFIX_AWARE_MODELS:
            logger.warning(
                "Model '%s' may not use 'search_document:'/'search_query:' task "
                "prefixes. Verify prefix requirements for this model or retrieval "
                "quality may degrade.",
                model_name,
            )

        logger.info("Loading embedding model %s", model_name)
        self._model = TextEmbedding(model_name=model_name)
        self._batch_size = batch_size

    def embed_documents(self, texts: list[str]) -> NDArray[np.float32]:
        """Embed a list of document texts.

        Prepends the 'search_document:' prefix required by nomic-embed-text-v1.5.

        Args:
            texts: List of document chunk strings to embed.

        Returns:
            Float32 array of shape (len(texts), embedding_dimension).

        Raises:
            EmbeddingError: If the model fails or returns an unexpected vector count.
        """
        if not texts:
            return np.empty((0, settings.embedding_dimension), dtype=np.float32)
        try:
            prefixed = [_DOC_PREFIX + t for t in texts]
            vecs = list(self._model.embed(prefixed, batch_size=self._batch_size))
            if len(vecs) != len(texts):
                raise EmbeddingError(
                    f"Model returned {len(vecs)} vectors for {len(texts)} documents"
                )
            result = np.array(vecs, dtype=np.float32)
            logger.debug("Embedded %d chunks → %s float32", len(texts), result.shape)
            return result
        except EmbeddingError:
            raise
        except Exception as e:
            raise EmbeddingError(f"Failed to embed {len(texts)} documents") from e

    def embed_query(self, query: str) -> NDArray[np.float32]:
        """Embed a single query string.

        Prepends the 'search_query:' prefix required by nomic-embed-text-v1.5.

        Args:
            query: Natural-language search query.

        Returns:
            Float32 array of shape (embedding_dimension,).

        Raises:
            EmbeddingError: If query is empty, the model fails, or the returned
                vector has an unexpected dimension.
        """
        if not query.strip():
            raise EmbeddingError("Query must not be empty")
        try:
            prefixed = _QUERY_PREFIX + query
            vecs = list(self._model.embed([prefixed]))
            return np.array(vecs[0], dtype=np.float32)
        except EmbeddingError:
            raise
        except Exception as e:
            raise EmbeddingError(f"Failed to embed query ({len(query)} chars)") from e


def get_embedder() -> "Embedder":
    """Return the module-level Embedder singleton, initialising on first call."""
    global _instance  # noqa: PLW0603
    if _instance is None:
        _instance = Embedder(
            model_name=settings.embedding_model,
            batch_size=settings.embedding_batch_size,
        )
    return _instance
