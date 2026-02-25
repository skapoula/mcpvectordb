"""Standalone CLI for bulk document ingestion without the MCP server."""

import argparse
import asyncio
import logging
import os
import sys

from mcpvectordb.chunker import _get_tokenizer
from mcpvectordb.config import settings
from mcpvectordb.embedder import get_embedder
from mcpvectordb.exceptions import IngestionError
from mcpvectordb.ingestor import ingest_folder
from mcpvectordb.store import Store


def main() -> None:
    """Entry point for the mcpvectordb-ingest CLI."""
    parser = argparse.ArgumentParser(
        prog="mcpvectordb-ingest",
        description="Bulk-ingest a folder of documents into the vector store.",
    )
    parser.add_argument("folder", help="Folder containing documents to ingest.")
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
        help="Do not scan subdirectories.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=4,
        help="Max files processed simultaneously. Default: 4.",
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

    try:
        result = asyncio.run(
            ingest_folder(
                folder=args.folder,
                library=args.library,
                metadata=None,
                store=Store(),
                recursive=args.recursive,
                max_concurrency=args.max_concurrency,
            )
        )
    except IngestionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nIngestion complete: {result.folder}")
    print(f"  Library   : {result.library}")
    print(f"  Found     : {result.total_files}")
    print(
        f"  Indexed   : {result.indexed}  Replaced: {result.replaced}  "
        f"Skipped: {result.skipped}  Failed: {result.failed}"
    )
    for err in result.errors:
        print(f"  ERROR  {err['file']}: {err['error']}", file=sys.stderr)
    sys.exit(1 if result.failed else 0)
