"""Token-aware recursive text chunking using a shared tokenizer singleton."""

import logging
from typing import TYPE_CHECKING

from mcpvectordb.config import settings

if TYPE_CHECKING:
    from transformers import PreTrainedTokenizerBase

logger = logging.getLogger(__name__)

_tokenizer: "PreTrainedTokenizerBase | None" = None

# Separator hierarchy for recursive splitting
_SEPARATORS = ["\n\n", "\n", " ", ""]


def _get_tokenizer() -> "PreTrainedTokenizerBase":
    """Return the module-level tokenizer singleton, initialising on first call."""
    global _tokenizer  # noqa: PLW0603
    if _tokenizer is None:
        from transformers import AutoTokenizer

        logger.info("Loading tokenizer for model %s", settings.embedding_model)
        _tokenizer = AutoTokenizer.from_pretrained(  # nosec B615 — from trusted config
            settings.embedding_model
        )
    return _tokenizer


def _token_length(text: str) -> int:
    """Return the number of tokens in *text* using the embedding tokenizer."""
    tok = _get_tokenizer()
    return len(tok.encode(text, add_special_tokens=False))


def _merge_splits(
    splits: list[str], separator: str, chunk_size: int, overlap: int
) -> list[str]:
    """Merge small splits into chunks respecting chunk_size and overlap."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for split in splits:
        split_len = _token_length(split)
        # If adding this split would exceed chunk_size, flush current
        if current_len + split_len > chunk_size and current:
            chunks.append(separator.join(current))
            # Keep overlap: drop splits from the front until under overlap budget
            while current and current_len > overlap:
                removed = current.pop(0)
                current_len -= _token_length(removed)
        current.append(split)
        current_len += split_len

    if current:
        chunks.append(separator.join(current))

    return chunks


def _split_recursive(
    text: str, separators: list[str], chunk_size: int, overlap: int
) -> list[str]:
    """Recursively split text using the first separator that produces usable pieces."""
    if not separators:
        # No more separators — return text as-is (may be oversized, caller filters)
        return [text]

    sep = separators[0]
    remaining = separators[1:]

    # Character-level split as last resort when sep is empty string
    splits = list(text) if sep == "" else text.split(sep)

    all_splits: list[str] = []
    for s in splits:
        if not s:
            continue
        if _token_length(s) > chunk_size:
            all_splits.extend(_split_recursive(s, remaining, chunk_size, overlap))
        else:
            all_splits.append(s)

    return _merge_splits(all_splits, sep if sep else "", chunk_size, overlap)


def chunk(text: str) -> list[str]:
    """Split *text* into token-bounded chunks suitable for embedding.

    Args:
        text: The Markdown text to split.

    Returns:
        List of chunk strings, each between chunk_min_tokens and chunk_size_tokens.
    """
    if not text.strip():
        return []

    raw_chunks = _split_recursive(
        text,
        _SEPARATORS,
        settings.chunk_size_tokens,
        settings.chunk_overlap_tokens,
    )
    filtered = [c for c in raw_chunks if _token_length(c) >= settings.chunk_min_tokens]

    if not filtered and raw_chunks:
        # Document is shorter than chunk_min_tokens — index it as a single chunk
        # rather than silently discarding it.
        logger.debug(
            "All chunks below min-token floor (%d); indexing as single chunk",
            settings.chunk_min_tokens,
        )
        filtered = [text.strip()]

    logger.debug(
        "Chunked text: %d raw → %d after min-token filter",
        len(raw_chunks),
        len(filtered),
    )
    return filtered
