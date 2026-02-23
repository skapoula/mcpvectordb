"""Pre-download the fastembed embedding model to the configured cache directory.

Run once after 'uv sync' to ensure the model is available before first use:

    uv run mcpvectordb-download-model

For PyInstaller builds, the build script calls this with FASTEMBED_CACHE_PATH
pointed at the build_models/ staging directory so the model is bundled in the .exe.
"""

import logging
import os
import sys
from pathlib import Path


def download_model() -> None:
    """Download the embedding model to the local cache.

    Reads FASTEMBED_CACHE_PATH from the environment (or settings) and ensures
    the model lands there rather than in fastembed's system default location.
    """
    from mcpvectordb.config import settings

    # Respect an explicitly set env var (e.g. from build script) first;
    # fall back to the configured fastembed_cache_path.
    cache_env = os.environ.get("FASTEMBED_CACHE_PATH")
    if not cache_env and settings.fastembed_cache_path:
        cache_path = Path(settings.fastembed_cache_path).expanduser()
        cache_path.mkdir(parents=True, exist_ok=True)
        os.environ["FASTEMBED_CACHE_PATH"] = str(cache_path)
        print(f"Model cache: {cache_path}")
    elif cache_env:
        Path(cache_env).mkdir(parents=True, exist_ok=True)
        print(f"Model cache (from env): {cache_env}")

    model_name = settings.embedding_model
    print(f"Downloading '{model_name}' (this only happens once)…")

    from fastembed import TextEmbedding

    # Instantiating triggers the download if the model is not already cached.
    TextEmbedding(model_name=model_name)
    print("Embedding model ready.")

    # Pre-download the HuggingFace tokenizer used by the chunker for token counting.
    # This is required — ingestion will fail if the tokenizer is not cached locally.
    print("Downloading tokenizer (nomic-ai/nomic-embed-text-v1.5)…")
    from transformers import AutoTokenizer

    AutoTokenizer.from_pretrained("nomic-ai/nomic-embed-text-v1.5")
    print("Tokenizer ready.")


def main() -> None:
    """Entry point for the mcpvectordb-download-model console script."""
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    download_model()


if __name__ == "__main__":
    main()
