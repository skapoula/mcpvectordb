"""Standalone CLI for document ingestion without the MCP server.

Accepts one or more file paths, folder paths, or a mix:

    mcpvectordb-ingest report.pdf                        # single file
    mcpvectordb-ingest a.pdf b.docx c.xlsx               # multiple files
    mcpvectordb-ingest /docs                             # folder (recursive)
    mcpvectordb-ingest a.pdf /docs /more-docs            # mixed
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from mcpvectordb.chunker import _get_tokenizer
from mcpvectordb.config import settings
from mcpvectordb.embedder import get_embedder
from mcpvectordb.exceptions import IngestionError, UnsupportedFormatError
from mcpvectordb.ingestor import ingest, ingest_folder
from mcpvectordb.store import Store

_Counts = tuple[int, int, int, int, int]  # total, indexed, replaced, skipped, failed


async def _ingest_file(path: Path, library: str, store: Store) -> _Counts:
    """Ingest a single file and print a one-line result."""
    try:
        result = await ingest(source=path, library=library, metadata=None, store=store)
        print(f"  {result.status.upper():<8} {path.name}  ({result.chunk_count} chunks)")
        counts = {"indexed": (1, 0, 0, 0), "replaced": (0, 1, 0, 0), "skipped": (0, 0, 1, 0)}
        i, r, s, f = counts.get(result.status, (0, 0, 0, 0))
        return 1, i, r, s, f
    except (IngestionError, UnsupportedFormatError) as e:
        print(f"  ERROR    {path.name}: {e}", file=sys.stderr)
        return 1, 0, 0, 0, 1


async def _ingest_dir(
    path: Path,
    library: str,
    recursive: bool,
    max_concurrency: int,
    store: Store,
) -> _Counts:
    """Ingest a folder and print a folder-level summary."""
    try:
        result = await ingest_folder(
            folder=path,
            library=library,
            metadata=None,
            store=store,
            recursive=recursive,
            max_concurrency=max_concurrency,
        )
        print(f"\n  Folder: {result.folder}")
        print(
            f"  Found: {result.total_files}  Indexed: {result.indexed}  "
            f"Replaced: {result.replaced}  Skipped: {result.skipped}  Failed: {result.failed}"
        )
        for err in result.errors:
            print(f"  ERROR  {err['file']}: {err['error']}", file=sys.stderr)
        return result.total_files, result.indexed, result.replaced, result.skipped, result.failed
    except IngestionError as e:
        print(f"Error: {path}: {e}", file=sys.stderr)
        return 1, 0, 0, 0, 1


async def _run(args: argparse.Namespace, store: Store) -> _Counts:
    """Dispatch ingestion for all paths on the command line."""
    total = indexed = replaced = skipped = failed = 0
    for raw in args.paths:
        path = Path(raw)
        if path.is_dir():
            t, i, r, s, f = await _ingest_dir(
                path, args.library, args.recursive, args.max_concurrency, store
            )
        elif path.is_file():
            t, i, r, s, f = await _ingest_file(path, args.library, store)
        else:
            print(f"Error: {raw}: path not found or not accessible", file=sys.stderr)
            t, i, r, s, f = 1, 0, 0, 0, 1
        total += t
        indexed += i
        replaced += r
        skipped += s
        failed += f
    return total, indexed, replaced, skipped, failed


def main() -> None:
    """Entry point for the mcpvectordb-ingest CLI."""
    parser = argparse.ArgumentParser(
        prog="mcpvectordb-ingest",
        description=(
            "Ingest files or folders into the vector store. "
            "Accepts one or more file paths, folder paths, or a mix of both."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Files or folders to ingest. Folders are scanned for supported formats.",
    )
    parser.add_argument(
        "--library",
        default=settings.default_library,
        help="Library name. Default: %(default)r.",
    )
    parser.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        default=True,
        help="Do not scan subdirectories (applies to folder inputs only).",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=4,
        help="Max files processed simultaneously (applies to folder inputs only). Default: 4.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

    print(f"Loading embedding model {settings.embedding_model!r} ...")
    get_embedder()
    _get_tokenizer()
    print("Models loaded. Starting ingestion ...")

    total, indexed, replaced, skipped, failed = asyncio.run(_run(args, Store()))

    print(f"\nIngestion complete.")
    print(f"  Library   : {args.library}")
    print(f"  Found     : {total}")
    print(
        f"  Indexed   : {indexed}  Replaced: {replaced}  "
        f"Skipped: {skipped}  Failed: {failed}"
    )
    sys.exit(1 if failed else 0)
