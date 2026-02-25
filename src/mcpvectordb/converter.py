"""Convert local files to Markdown text via MarkItDown."""

import logging
from pathlib import Path

from markitdown import MarkItDown

from mcpvectordb.exceptions import UnsupportedFormatError

logger = logging.getLogger(__name__)

# Extensions MarkItDown[all] can handle. Checked before calling to give a clear error.
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xls",
    ".html",
    ".htm",
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".xml",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".mp3",
    ".wav",
    ".ogg",
    ".m4a",
    ".zip",
}

_md = MarkItDown()


def convert(source: Path) -> str:
    """Convert a local file to Markdown text.

    Args:
        source: Path to the local file to convert.

    Returns:
        Markdown text extracted from the file.

    Raises:
        UnsupportedFormatError: If the file extension is not supported.
        IngestionError: If MarkItDown fails to convert the file.
    """
    ext = source.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"Unsupported file extension: {ext!r}. "
            f"Supported: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    logger.debug("Converting %s (ext=%s)", source, ext)
    result = _md.convert(str(source))
    text = result.text_content or ""
    logger.debug("Converted %s → %d chars", source, len(text))
    return text
