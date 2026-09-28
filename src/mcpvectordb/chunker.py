"""Token-aware recursive text chunking using a shared tokenizer singleton."""

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel

from mcpvectordb.config import settings

if TYPE_CHECKING:
    from transformers import PreTrainedTokenizerBase

logger = logging.getLogger(__name__)

_tokenizer: "PreTrainedTokenizerBase | None" = None

# Separator hierarchy for recursive splitting
_SEPARATORS = ["\n\n", "\n", " ", ""]


class Chunk(BaseModel):
    """One chunk of a document and how much of the previous chunk it repeats."""

    text: str
    # Leading characters of text copied from the end of the previous chunk;
    # 0 when the chunk starts fresh (first chunk, new page, new split group).
    overlap: int = 0


def _get_tokenizer() -> "PreTrainedTokenizerBase":
    """Return the tokenizer singleton, loading it on first call.

    Uses settings.embedding_model as the HuggingFace Hub model ID so the
    tokenizer always matches the configured embedding model.

    Raises:
        RuntimeError: If the tokenizer is not cached locally. Run
            'uv run mcpvectordb-download-model' to download it.
    """
    global _tokenizer  # noqa: PLW0603
    if _tokenizer is None:
        from transformers import AutoTokenizer

        model_id = settings.embedding_model
        logger.info("Loading tokenizer %s", model_id)
        try:
            _tokenizer = AutoTokenizer.from_pretrained(  # nosec B615
                model_id, local_files_only=True, trust_remote_code=True
            )
        except Exception as exc:
            raise RuntimeError(
                f"Tokenizer '{model_id}' is not in the local cache. "
                "Run 'uv run mcpvectordb-download-model' to download it, "
                "then restart the server."
            ) from exc
    return _tokenizer


def _token_length(text: str) -> int:
    """Return the number of tokens in *text* using the embedding tokenizer."""
    tok = _get_tokenizer()
    return len(tok.encode(text, add_special_tokens=False))


def _token_offsets(text: str) -> list[tuple[int, int]]:
    """Return (start, end) character offsets of each token in *text*.

    Slicing the original text by these offsets keeps case, punctuation and
    spacing intact, which tokenizer.decode() does not (uncased tokenizers
    lowercase and re-space it).
    """
    enc = _get_tokenizer()(text, add_special_tokens=False, return_offsets_mapping=True)
    return list(enc["offset_mapping"])


def _tail(text: str, n_tokens: int) -> str:
    """Return roughly the last *n_tokens* tokens of *text*, starting on a word."""
    offsets = _token_offsets(text)
    if len(offsets) <= n_tokens:
        return text
    tail = text[offsets[-n_tokens][0] :]
    space = tail.find(" ")
    return tail[space + 1 :] if 0 <= space < len(tail) - 1 else tail


def _merge_splits(
    splits: list[str], separator: str, chunk_size: int, overlap: int
) -> list[Chunk]:
    """Merge small splits into chunks respecting chunk_size and overlap.

    Token lengths for each split are cached to avoid redundant tokenizer calls
    during overlap trimming. Separator tokens are counted in the assembled
    chunk length so the configured limit is never silently exceeded.
    """
    sep_len = _token_length(separator) if separator else 0
    chunks: list[Chunk] = []
    current: list[str] = []
    lengths: list[int] = []  # cached token lengths, parallel to current
    current_len = 0
    carried = 0  # characters of current copied from the previous chunk

    for split in splits:
        split_len = _token_length(split)
        # Separator tokens added before this split when current is non-empty
        sep_addition = sep_len if current else 0
        # If adding this split would exceed chunk_size, flush current
        if current_len + sep_addition + split_len > chunk_size and current:
            chunks.append(Chunk(text=separator.join(current), overlap=carried))
            # Keep overlap: drop splits from the front until under overlap budget
            while current and current_len > overlap:
                removed_len = lengths.pop(0)
                current.pop(0)
                current_len -= removed_len
                if current:
                    # The separator that preceded this element is also gone
                    current_len -= sep_len
            # A single split longer than the overlap budget trims to nothing;
            # seed the next chunk with the previous chunk's tail instead.
            if not current and overlap > 0:
                tail = _tail(chunks[-1].text, overlap)
                tail_len = _token_length(tail)
                if tail_len + sep_len + split_len <= chunk_size:
                    current, lengths, current_len = [tail], [tail_len], tail_len
            # What survived trimming is a suffix of the chunk just flushed.
            carried = len(separator.join(current))
            # Recalculate sep_addition after overlap trimming
            sep_addition = sep_len if current else 0
        current.append(split)
        lengths.append(split_len)
        current_len += sep_addition + split_len

    if current:
        chunks.append(Chunk(text=separator.join(current), overlap=carried))

    return chunks


def _split_recursive(
    text: str, separators: list[str], chunk_size: int, overlap: int
) -> list[Chunk]:
    """Recursively split text using the first separator that produces usable pieces.

    Sub-pieces that required recursion are not re-joined with the parent separator;
    they are flushed as independent chunks to preserve the separator that was
    actually used at each recursion level.

    For the character-level fallback (empty separator), the text is encoded once
    and sliced by token offsets to avoid O(n) per-character tokenizer calls.
    """
    if not separators:
        # No more separators — return text as-is (may be oversized, caller filters)
        return [Chunk(text=text)]

    sep = separators[0]
    remaining = separators[1:]

    # Character-level last resort: tokenize once and slice token windows.
    if sep == "":
        offsets = _token_offsets(text)
        if len(offsets) <= chunk_size:
            return [Chunk(text=text)]
        step = max(1, chunk_size - overlap)
        windows: list[Chunk] = []
        prev_end = 0
        # A window starting within the last `overlap` tokens lies wholly inside
        # the previous window, so stop before emitting it.
        for i in range(0, len(offsets) - overlap, step):
            start = offsets[i][0]
            end = offsets[min(i + chunk_size, len(offsets)) - 1][1]
            windows.append(
                Chunk(text=text[start:end], overlap=max(0, prev_end - start))
            )
            prev_end = end
        return windows

    splits = text.split(sep)

    # Separate direct (small) splits from oversized ones that need recursion.
    # Flush good_splits before appending recursed output so each group is merged
    # with the separator that was actually used to produce its pieces.
    final_chunks: list[Chunk] = []
    good_splits: list[str] = []

    for s in splits:
        if not s:
            continue
        if _token_length(s) > chunk_size:
            if good_splits:
                final_chunks.extend(
                    _merge_splits(good_splits, sep, chunk_size, overlap)
                )
                good_splits = []
            final_chunks.extend(_split_recursive(s, remaining, chunk_size, overlap))
        else:
            good_splits.append(s)

    if good_splits:
        final_chunks.extend(_merge_splits(good_splits, sep, chunk_size, overlap))

    return final_chunks


def _append(prev: Chunk, nxt: Chunk) -> str:
    """Return the text of *prev* followed by what *nxt* adds after it."""
    if nxt.overlap:
        return prev.text + nxt.text[nxt.overlap :]
    return prev.text + "\n\n" + nxt.text


def _merge_short(chunks: list[Chunk]) -> list[Chunk]:
    """Fold chunks below chunk_min_tokens into a neighbour instead of dropping them."""
    out: list[Chunk] = []
    for c in chunks:
        if out:
            merged = _append(out[-1], c)
            short = min(_token_length(c.text), _token_length(out[-1].text))
            if (
                short < settings.chunk_min_tokens
                and _token_length(merged) <= settings.chunk_size_tokens
            ):
                out[-1] = Chunk(text=merged, overlap=out[-1].overlap)
                continue
        out.append(c)
    return out


def chunk_with_overlap(text: str) -> list[Chunk]:
    """Split *text* into token-bounded chunks, recording each chunk's overlap.

    Args:
        text: The Markdown text to split.

    Returns:
        Chunks of at most chunk_size_tokens each. A chunk stays below
        chunk_min_tokens only when no neighbour has room to absorb it.
    """
    if not text.strip():
        return []

    raw_chunks = _split_recursive(
        text,
        _SEPARATORS,
        settings.chunk_size_tokens,
        settings.chunk_overlap_tokens,
    )
    merged = _merge_short(raw_chunks)

    logger.debug(
        "Chunked text: %d raw → %d after merging short chunks",
        len(raw_chunks),
        len(merged),
    )
    return merged


def chunk(text: str) -> list[str]:
    """Split *text* into token-bounded chunk strings suitable for embedding.

    Args:
        text: The Markdown text to split.

    Returns:
        The texts of chunk_with_overlap(text).
    """
    return [c.text for c in chunk_with_overlap(text)]


def join_chunks(chunks: list[Chunk]) -> str:
    """Rebuild a document from its chunks in order, using each recorded overlap.

    Chunks with overlap 0 (a new page, a new split group, or rows indexed
    before overlap was recorded) are joined with a blank line, so their text
    is repeated rather than guessed away. Whitespace at such a boundary may
    differ from the source.

    Args:
        chunks: The document's chunks in chunk_index order.

    Returns:
        The rebuilt document text.
    """
    if not chunks:
        return ""
    parts = [chunks[0].text]
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        parts.append(_append(prev, nxt)[len(prev.text) :])
    return "".join(parts)
