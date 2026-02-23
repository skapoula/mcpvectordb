"""Orchestrates the ingestion pipeline: fetch/read → convert → chunk → embed → store."""

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import BaseModel

from mcpvectordb.chunker import chunk
from mcpvectordb.config import settings
from mcpvectordb.converter import convert
from mcpvectordb.embedder import get_embedder
from mcpvectordb.exceptions import IngestionError, UnsupportedFormatError
from mcpvectordb.store import ChunkRecord, Store

logger = logging.getLogger(__name__)


class IngestResult(BaseModel):
    """Result returned from a single ingest call."""

    status: str  # "indexed" | "replaced" | "skipped"
    doc_id: str
    source: str
    library: str
    chunk_count: int


async def ingest(
    source: Path | str,
    library: str,
    metadata: dict | None,
    store: Store,
) -> IngestResult:
    """Run the full ingestion pipeline for a local file or URL.

    Args:
        source: Local Path or URL string to ingest.
        library: Library name to index the document under.
        metadata: Optional user-supplied key-value metadata.
        store: Store instance to write chunks to.

    Returns:
        IngestResult describing what happened (indexed / replaced / skipped).

    Raises:
        IngestionError: If fetching, converting, chunking, or storing fails.
        UnsupportedFormatError: If the file format is not supported.
    """
    is_url = isinstance(source, str) and source.startswith(("http://", "https://"))
    source_str = str(source)
    meta_json = json.dumps(metadata or {})

    # ── 1. Fetch raw bytes ─────────────────────────────────────────────────────
    if is_url:
        raw_bytes, last_modified = await _fetch_url(source_str)
        file_type = "url"
    else:
        path = Path(source) if not isinstance(source, Path) else source
        try:
            raw_bytes = await asyncio.to_thread(path.read_bytes)
        except OSError as e:
            raise IngestionError(f"Cannot read file {source_str!r}") from e
        file_type = path.suffix.lstrip(".").lower() or "unknown"
        try:
            mtime = path.stat().st_mtime
            last_modified = datetime.fromtimestamp(mtime, UTC).isoformat()
        except OSError:
            last_modified = ""

    # ── 2. Dedup check ─────────────────────────────────────────────────────────
    new_hash = hashlib.sha256(raw_bytes).hexdigest()
    existing_doc_id, existing_hash = await asyncio.to_thread(
        store.find_existing, source_str, library
    )

    if existing_hash == new_hash:
        logger.info(
            "Skipping %s — content unchanged (hash=%s)", source_str, new_hash[:8]
        )
        return IngestResult(
            status="skipped",
            doc_id=existing_doc_id or "",
            source=source_str,
            library=library,
            chunk_count=0,
        )

    if existing_doc_id is not None:
        logger.info(
            "Replacing %s in library %r (doc_id=%s)",
            source_str,
            library,
            existing_doc_id,
        )
        await asyncio.to_thread(store.delete_document, existing_doc_id)
        ingest_status = "replaced"
    else:
        ingest_status = "indexed"

    # ── 3. Convert to Markdown ─────────────────────────────────────────────────
    if is_url:
        text = await _convert_html_bytes(raw_bytes, source_str)
    else:
        path = Path(source) if not isinstance(source, Path) else source
        try:
            text = await asyncio.to_thread(convert, path)
        except UnsupportedFormatError:
            raise
        except Exception as e:
            raise IngestionError(f"Conversion failed for {source_str!r}") from e

    if not text.strip():
        raise IngestionError(
            f"No text could be extracted from {source_str!r}. "
            "The file may be scanned/image-based, password-protected, or empty. "
            "Try ingest_content to pass the text directly."
        )

    title = _extract_title(text, source_str)

    # ── 4. Chunk ───────────────────────────────────────────────────────────────
    try:
        chunks = await asyncio.to_thread(chunk, text)
    except Exception as e:
        raise IngestionError(f"Chunking failed for {source_str!r}") from e

    if not chunks:
        raise IngestionError(f"No usable chunks produced from {source_str!r}")

    # ── 5. Embed ───────────────────────────────────────────────────────────────
    try:
        embeddings = await asyncio.to_thread(get_embedder().embed_documents, chunks)
    except Exception as e:
        raise IngestionError(f"Embedding failed for {source_str!r}") from e

    # ── 6. Build records and store ─────────────────────────────────────────────
    doc_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    records = [
        ChunkRecord(
            id=str(uuid.uuid4()),
            doc_id=doc_id,
            library=library,
            source=source_str,
            content_hash=new_hash,
            title=title,
            content=chunk_text,
            embedding=embeddings[i].tolist(),
            chunk_index=i,
            created_at=now,
            metadata=meta_json,
            file_type=file_type,
            last_modified=last_modified,
            page=0,
        )
        for i, chunk_text in enumerate(chunks)
    ]

    try:
        await asyncio.to_thread(store.upsert_chunks, records)
    except Exception as e:
        raise IngestionError(f"Store write failed for {source_str!r}") from e

    logger.info(
        "%s %s → %d chunks in library %r (doc_id=%s)",
        ingest_status,
        source_str,
        len(records),
        library,
        doc_id,
    )
    return IngestResult(
        status=ingest_status,
        doc_id=doc_id,
        source=source_str,
        library=library,
        chunk_count=len(records),
    )


async def ingest_content(
    content: str,
    source: str,
    library: str,
    metadata: dict | None,
    store: Store,
) -> IngestResult:
    """Ingest pre-extracted text content directly, skipping fetch and conversion.

    Use this when the caller (e.g. Claude Desktop) has already read and extracted
    the text from a file — for example, from a user-uploaded attachment that is not
    accessible on the server's filesystem.

    Args:
        content: The Markdown or plain-text content to index.
        source: A human-readable identifier for the source (filename, URL, label).
        library: Library name to index the document under.
        metadata: Optional user-supplied key-value metadata.
        store: Store instance to write chunks to.

    Returns:
        IngestResult describing what happened (indexed / replaced / skipped).

    Raises:
        IngestionError: If chunking, embedding, or storing fails.
    """
    source_str = source.strip() or "uploaded-content"
    meta_json = json.dumps(metadata or {})
    raw_bytes = content.encode()

    # ── 1. Dedup check ─────────────────────────────────────────────────────────
    new_hash = hashlib.sha256(raw_bytes).hexdigest()
    existing_doc_id, existing_hash = await asyncio.to_thread(
        store.find_existing, source_str, library
    )

    if existing_hash == new_hash:
        logger.info(
            "Skipping %s — content unchanged (hash=%s)", source_str, new_hash[:8]
        )
        return IngestResult(
            status="skipped",
            doc_id=existing_doc_id or "",
            source=source_str,
            library=library,
            chunk_count=0,
        )

    if existing_doc_id is not None:
        logger.info(
            "Replacing %s in library %r (doc_id=%s)",
            source_str,
            library,
            existing_doc_id,
        )
        await asyncio.to_thread(store.delete_document, existing_doc_id)
        ingest_status = "replaced"
    else:
        ingest_status = "indexed"

    title = _extract_title(content, source_str)
    file_type = source_str.rsplit(".", 1)[-1].lower() if "." in source_str else "text"
    now = datetime.now(UTC).isoformat()

    # ── 2. Chunk ───────────────────────────────────────────────────────────────
    try:
        chunks = await asyncio.to_thread(chunk, content)
    except Exception as e:
        raise IngestionError(f"Chunking failed for {source_str!r}") from e

    if not chunks:
        raise IngestionError(f"No usable chunks produced from {source_str!r}")

    # ── 3. Embed ───────────────────────────────────────────────────────────────
    try:
        embeddings = await asyncio.to_thread(get_embedder().embed_documents, chunks)
    except Exception as e:
        raise IngestionError(f"Embedding failed for {source_str!r}") from e

    # ── 4. Build records and store ─────────────────────────────────────────────
    doc_id = str(uuid.uuid4())

    records = [
        ChunkRecord(
            id=str(uuid.uuid4()),
            doc_id=doc_id,
            library=library,
            source=source_str,
            content_hash=new_hash,
            title=title,
            content=chunk_text,
            embedding=embeddings[i].tolist(),
            chunk_index=i,
            created_at=now,
            metadata=meta_json,
            file_type=file_type,
            last_modified=now,
            page=0,
        )
        for i, chunk_text in enumerate(chunks)
    ]

    try:
        await asyncio.to_thread(store.upsert_chunks, records)
    except Exception as e:
        raise IngestionError(f"Store write failed for {source_str!r}") from e

    logger.info(
        "%s %s → %d chunks in library %r (doc_id=%s)",
        ingest_status,
        source_str,
        len(records),
        library,
        doc_id,
    )
    return IngestResult(
        status=ingest_status,
        doc_id=doc_id,
        source=source_str,
        library=library,
        chunk_count=len(records),
    )


async def _fetch_url(url: str) -> tuple[bytes, str]:
    """Fetch a URL and return its raw bytes and last-modified timestamp.

    Args:
        url: The URL to fetch.

    Returns:
        Tuple of (raw response bytes, ISO 8601 last-modified string or "").

    Raises:
        IngestionError: On network error or non-2xx status.
    """
    try:
        async with httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": settings.http_user_agent},
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            last_modified = response.headers.get("last-modified", "")
            return response.content, last_modified
    except httpx.HTTPStatusError as e:
        raise IngestionError(f"HTTP {e.response.status_code} fetching {url!r}") from e
    except httpx.RequestError as e:
        raise IngestionError(f"Network error fetching {url!r}") from e


async def _convert_html_bytes(raw_bytes: bytes, source_str: str) -> str:
    """Convert raw HTML bytes to Markdown using MarkItDown.

    Args:
        raw_bytes: Raw HTTP response body.
        source_str: Original URL (used for logging).

    Returns:
        Markdown text.

    Raises:
        IngestionError: If conversion fails.
    """
    import tempfile

    from markitdown import MarkItDown

    try:
        # Write bytes to a temp file with .html extension so MarkItDown uses HTML parser
        def _convert() -> str:
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tf:
                tf.write(raw_bytes)
                tf_path = tf.name
            try:
                md = MarkItDown()
                result = md.convert(tf_path)
                return result.text_content or ""
            finally:
                import os

                os.unlink(tf_path)

        return await asyncio.to_thread(_convert)
    except Exception as e:
        raise IngestionError(f"HTML conversion failed for {source_str!r}") from e


def _extract_title(text: str, source: str) -> str:
    """Infer a document title from the first Markdown heading or source path.

    Args:
        text: Markdown text.
        source: Source path or URL (used as fallback).

    Returns:
        A short title string.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:200]
    # Fallback: last path component
    return source.split("/")[-1].split("\\")[-1][:200]
