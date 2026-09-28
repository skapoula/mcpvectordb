"""Convert local files to Markdown text via MarkItDown."""

import logging
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from mcpvectordb.exceptions import IngestionError, UnsupportedFormatError

if TYPE_CHECKING:
    from markitdown import MarkItDown

logger = logging.getLogger(__name__)

# Extensions that convert to usable text. Checked before calling for a clear error.
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".xls",
    ".html",
    ".htm",
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".xml",
    ".zip",
}

_NO_OCR = "images carry no text without OCR; run an OCR tool and ingest its text"
_CLOUD_AUDIO = (
    "audio transcription sends the recording to Google's speech service, "
    "so audio is not ingested; transcribe it locally and ingest the text"
)

# Formats MarkItDown accepts but cannot turn into text here, with the reason.
_NO_TEXT_FORMATS = {
    ".doc": "legacy Word format has no converter; save it as .docx",
    ".ppt": "legacy PowerPoint format has no converter; save it as .pptx",
    **dict.fromkeys((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"), _NO_OCR),
    **dict.fromkeys((".mp3", ".wav", ".ogg", ".m4a"), _CLOUD_AUDIO),
}

_md: "MarkItDown | None" = None


def _get_markitdown() -> "MarkItDown":
    """Return the MarkItDown singleton, initialising on first call."""
    global _md  # noqa: PLW0603
    if _md is None:
        from markitdown import MarkItDown

        _md = MarkItDown()
    return _md


def _check_zip_members(archive: Path) -> None:
    """Refuse a ZIP holding audio: MarkItDown would transcribe it via the cloud."""
    try:
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise IngestionError(f"Cannot read ZIP {archive.name!r}: {exc}") from exc
    for name in names:
        if _NO_TEXT_FORMATS.get(Path(name).suffix.lower()) == _CLOUD_AUDIO:
            raise UnsupportedFormatError(
                f"Cannot ingest {archive.name!r}: it contains {name!r}; {_CLOUD_AUDIO}."
            )


def convert(source: Path) -> str:
    """Convert a local file to Markdown text.

    Args:
        source: Path to the local file to convert.

    Returns:
        Markdown text extracted from the file, or an empty string if the
        file contains no extractable text content.

    Raises:
        UnsupportedFormatError: If the file has no extension or an unsupported one.
        IngestionError: If MarkItDown fails to convert the file.
    """
    source = source.resolve()
    ext = source.suffix.lower()

    if ext == "":
        raise UnsupportedFormatError(
            f"No file extension detected for {source.name!r} — cannot determine format."
        )
    if ext in _NO_TEXT_FORMATS:
        raise UnsupportedFormatError(
            f"Cannot ingest {source.name!r}: {_NO_TEXT_FORMATS[ext]}."
        )
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"Unsupported file extension: {ext!r}. "
            f"Supported: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    if ext == ".zip":
        _check_zip_members(source)

    logger.debug("Converting %s (ext=%s)", source, ext)
    try:
        result = _get_markitdown().convert(str(source))
        text = result.text_content or ""
    except Exception as exc:
        raise IngestionError(f"Failed to convert {source.name!r}: {exc}") from exc

    if not text:
        logger.warning("Converted %s produced empty text content", source)
    else:
        logger.debug("Converted %s → %d chars", source, len(text))
    return text
