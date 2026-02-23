"""MCP server entry point — registers tools and selects transport."""

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from mcpvectordb.config import settings
from mcpvectordb.converter import convert as _convert
from mcpvectordb.embedder import get_embedder
from mcpvectordb.exceptions import IngestionError, StoreError, UnsupportedFormatError
from mcpvectordb.ingestor import ingest
from mcpvectordb.ingestor import ingest_content as _ingest_content
from mcpvectordb.store import Store

# ── Logging setup ──────────────────────────────────────────────────────────────
# In stdio mode every byte on stdout corrupts MCP framing — log to stderr only.
_log_handlers: list[logging.Handler] = []
if settings.log_file:
    _log_handlers.append(logging.FileHandler(Path(settings.log_file).expanduser()))
_log_handlers.append(logging.StreamHandler(sys.stderr))

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    handlers=_log_handlers,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# When extra allowed hosts are configured (e.g. a tailscale/nginx hostname),
# extend the default localhost allowlist so DNS rebinding protection still applies.
_transport_security: TransportSecuritySettings | None = None
if settings.allowed_hosts_list:
    _scheme = "https" if settings.tls_enabled else "http"
    _transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"] + settings.allowed_hosts_list,
        allowed_origins=[
            f"{_scheme}://127.0.0.1:*",
            f"{_scheme}://localhost:*",
            f"{_scheme}://[::1]:*",
        ],
    )

mcp = FastMCP(
    "mcpvectordb",
    host=settings.mcp_host,
    port=settings.mcp_port,
    transport_security=_transport_security,
)
_store = Store()


# ── Tool: ingest_file ──────────────────────────────────────────────────────────
@mcp.tool()
async def ingest_file(
    path: str,
    library: str = "default",
    metadata: dict | None = None,
) -> dict:
    """Ingest a local file into the vector index.

    Converts the file to Markdown, chunks it, embeds each chunk, and stores
    everything in LanceDB. Deduplicates by (path, library) and content hash.

    Args:
        path: Absolute or relative path to the file to ingest.
        library: Library (collection) name. Defaults to 'default'.
        metadata: Optional key-value metadata to attach to the document.

    Returns:
        Dict with status, doc_id, source, library, chunk_count.
    """
    try:
        result = await ingest(
            source=Path(path).expanduser().resolve(),
            library=library,
            metadata=metadata,
            store=_store,
        )
        return result.model_dump()
    except UnsupportedFormatError as e:
        return {"error": f"Unsupported format: {e}", "status": "error"}
    except IngestionError as e:
        return {"error": f"Ingestion failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in ingest_file")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Tool: ingest_url ──────────────────────────────────────────────────────────
@mcp.tool()
async def ingest_url(
    url: str,
    library: str = "default",
    metadata: dict | None = None,
) -> dict:
    """Fetch a URL and ingest its content into the vector index.

    Downloads the page, converts HTML to Markdown, chunks, embeds, and stores.
    Deduplicates by (url, library) and content hash.

    Args:
        url: HTTP or HTTPS URL to fetch and ingest.
        library: Library (collection) name. Defaults to 'default'.
        metadata: Optional key-value metadata to attach to the document.

    Returns:
        Dict with status, doc_id, source, library, chunk_count.
    """
    if not url.startswith(("http://", "https://")):
        return {"error": "URL must start with http:// or https://", "status": "error"}
    try:
        result = await ingest(
            source=url,
            library=library,
            metadata=metadata,
            store=_store,
        )
        return result.model_dump()
    except IngestionError as e:
        return {"error": f"Ingestion failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in ingest_url")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Tool: ingest_content ───────────────────────────────────────────────────────
@mcp.tool()
async def ingest_content(
    content: str,
    source: str,
    library: str = "default",
    metadata: dict | None = None,
) -> dict:
    """Ingest text content directly, without reading from the filesystem.

    Use this when you have already extracted or read the text — for example,
    when a user uploads a file to Claude Desktop that the server cannot access
    on disk. Read the file content yourself and pass it here as a string.

    Args:
        content: The full text or Markdown to index.
        source: A label identifying the origin (e.g. filename or URL). Used for
            deduplication and display in search results.
        library: Library (collection) name. Defaults to 'default'.
        metadata: Optional key-value metadata to attach to the document.

    Returns:
        Dict with status, doc_id, source, library, chunk_count.
    """
    if not content or not content.strip():
        return {"error": "content must not be empty", "status": "error"}
    try:
        result = await _ingest_content(
            content=content,
            source=source,
            library=library,
            metadata=metadata,
            store=_store,
        )
        return result.model_dump()
    except IngestionError as e:
        return {"error": f"Ingestion failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in ingest_content")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Tool: search ──────────────────────────────────────────────────────────────
@mcp.tool()
async def search(
    query: str,
    top_k: int = 5,
    library: str | None = None,
    filter: dict | None = None,  # noqa: A002
) -> dict:
    """Hybrid search (BM25 + vector) over the indexed document library.

    Embeds the query for semantic search and uses the raw text for BM25 full-text
    search, combining both via reciprocal rank fusion for improved retrieval.

    Args:
        query: Natural language search query.
        top_k: Maximum number of results to return (default 5).
        library: Restrict search to this library. Searches all if None.
        filter: Optional equality filters applied before ranking.
            Supported keys: any ChunkRecord field (e.g. ``file_type``, ``page``).
            Example: ``{"file_type": "pdf"}`` or ``{"page": 3}``.

    Returns:
        Dict with 'results' list of matching chunks.
    """
    if not query.strip():
        return {"error": "query must not be empty", "status": "error"}
    if top_k < 1 or top_k > 100:
        return {"error": "top_k must be between 1 and 100", "status": "error"}
    try:
        import asyncio

        embedding = await asyncio.to_thread(get_embedder().embed_query, query)
        records = _store.search(
            embedding=embedding.tolist(),
            query_text=query,
            top_k=top_k,
            library=library,
            filter=filter,
        )
        return {
            "results": [
                {
                    "doc_id": r.doc_id,
                    "source": r.source,
                    "title": r.title,
                    "library": r.library,
                    "file_type": r.file_type,
                    "last_modified": r.last_modified,
                    "page": r.page,
                    "content": r.content,
                    "chunk_index": r.chunk_index,
                    "metadata": json.loads(r.metadata),
                }
                for r in records
            ]
        }
    except StoreError as e:
        return {"error": f"Search failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in search")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Tool: list_documents ──────────────────────────────────────────────────────
@mcp.tool()
async def list_documents(
    library: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """List indexed documents with metadata.

    Args:
        library: Filter by library name. Returns all libraries if None.
        limit: Maximum number of documents to return (default 20).
        offset: Number of documents to skip for pagination.

    Returns:
        Dict with 'documents' list and 'total' count.
    """
    if limit < 1 or limit > 1000:
        return {"error": "limit must be between 1 and 1000", "status": "error"}
    if offset < 0:
        return {"error": "offset must be non-negative", "status": "error"}
    try:
        docs = _store.list_documents(library=library, limit=limit, offset=offset)
        return {"documents": docs, "count": len(docs)}
    except StoreError as e:
        return {"error": f"list_documents failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in list_documents")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Tool: list_libraries ──────────────────────────────────────────────────────
@mcp.tool()
async def list_libraries() -> dict:
    """List all libraries with document and chunk counts.

    Returns:
        Dict with 'libraries' list. Each entry has library, document_count, chunk_count.
    """
    try:
        libs = _store.list_libraries()
        return {"libraries": libs}
    except StoreError as e:
        return {"error": f"list_libraries failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in list_libraries")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Tool: delete_document ─────────────────────────────────────────────────────
@mcp.tool()
async def delete_document(doc_id: str) -> dict:
    """Remove a document and all its chunks from the index.

    Args:
        doc_id: The document UUID to delete.

    Returns:
        Dict with deleted_chunks count.
    """
    if not doc_id.strip():
        return {"error": "doc_id must not be empty", "status": "error"}
    try:
        deleted = _store.delete_document(doc_id)
        return {"doc_id": doc_id, "deleted_chunks": deleted, "status": "deleted"}
    except StoreError as e:
        return {"error": f"delete_document failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in delete_document")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Tool: get_document ────────────────────────────────────────────────────────
@mcp.tool()
async def get_document(doc_id: str) -> dict:
    """Return the full Markdown text of an indexed document.

    Concatenates all chunks in order to reconstruct the document text.

    Args:
        doc_id: The document UUID to retrieve.

    Returns:
        Dict with doc_id, source, title, library, content (full text), chunk_count.
    """
    if not doc_id.strip():
        return {"error": "doc_id must not be empty", "status": "error"}
    try:
        records = _store.get_document(doc_id)
        if not records:
            return {"error": f"Document not found: {doc_id}", "status": "error"}
        first = records[0]
        full_text = "\n\n".join(r.content for r in records)
        return {
            "doc_id": doc_id,
            "source": first.source,
            "title": first.title,
            "library": first.library,
            "content": full_text,
            "chunk_count": len(records),
            "metadata": json.loads(first.metadata),
        }
    except StoreError as e:
        return {"error": f"get_document failed: {e}", "status": "error"}
    except Exception as e:
        logger.exception("Unexpected error in get_document")
        return {"error": f"Internal error: {e}", "status": "error"}


# ── Tool: server_info ─────────────────────────────────────────────────────────
@mcp.tool()
async def server_info(check_path: str | None = None) -> dict:
    """Return server diagnostics useful for verifying the installation.

    Reports the server's platform, working directory, Python version, and the
    resolved paths it uses for the vector store and embedding model cache.

    Optionally checks whether a specific file path is readable by the server —
    pass the path you want to ingest and the server will confirm whether it can
    see and read that file before you attempt ingestion.

    Args:
        check_path: Optional file path to test for readability. The server will
            report whether the file exists and how large it is. Use this to
            diagnose 'file not found' errors before calling ingest_file.

    Returns:
        Dict with platform, cwd, python_version, lancedb_uri,
        fastembed_cache_path, transport, and optionally path_check.
    """
    import os

    info: dict[str, Any] = {
        "platform": sys.platform,
        "python_version": sys.version.split()[0],
        "cwd": str(Path.cwd()),
        "lancedb_uri": str(Path(settings.lancedb_uri).expanduser().resolve()),
        "fastembed_cache_path": str(
            Path(settings.fastembed_cache_path).expanduser().resolve()
        )
        if settings.fastembed_cache_path
        else None,
        "transport": settings.mcp_transport,
        "note": (
            "In stdio mode the server runs on the same machine as Claude Desktop "
            "with the same user permissions. Use check_path to verify a specific "
            "file is reachable before calling ingest_file."
        ),
    }

    if check_path:
        resolved = Path(check_path).expanduser().resolve()
        parent_exists = resolved.parent.exists()
        base: dict[str, Any] = {
            "received": check_path,        # raw string the server got
            "resolved": str(resolved),     # after expanduser + resolve
            "parent_exists": parent_exists,
        }
        if resolved.exists():
            try:
                size = resolved.stat().st_size
                # Confirm read permission by opening briefly
                with resolved.open("rb") as fh:
                    fh.read(1)
                info["path_check"] = {**base, "readable": True, "size_bytes": size}
            except OSError as e:
                info["path_check"] = {**base, "readable": False, "error": str(e)}
        else:
            info["path_check"] = {
                **base,
                "readable": False,
                "error": (
                    "File does not exist at resolved path. "
                    "Check 'received' to see exactly what the server got — "
                    "special characters like & may have been truncated by "
                    "the AI layer. If so, rename the file to remove them."
                ),
            }

    return info


# ── HTTP upload endpoint ───────────────────────────────────────────────────────
@mcp.custom_route("/upload", methods=["POST"])
async def upload_handler(request: Request) -> JSONResponse:
    """Accept multipart file upload and run the full ingest pipeline on the server.

    Form fields:
        file     — binary file to ingest (required)
        library  — library name (optional, defaults to DEFAULT_LIBRARY)
        metadata — JSON string of key-value pairs (optional)
    """
    try:
        form = await request.form(max_part_size=settings.max_upload_bytes)
    except Exception as e:
        return JSONResponse(
            {"status": "error", "error": f"Form parse failed: {e}"}, status_code=400
        )

    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        return JSONResponse(
            {"status": "error", "error": "Missing required 'file' field"},
            status_code=400,
        )

    filename = getattr(upload, "filename", None) or "upload"
    suffix = Path(filename).suffix or ".bin"
    library = str(form.get("library") or settings.default_library)

    raw_meta = form.get("metadata")
    try:
        metadata = json.loads(raw_meta) if raw_meta else None
    except ValueError:
        return JSONResponse(
            {"status": "error", "error": "'metadata' must be a valid JSON string"},
            status_code=400,
        )

    raw_bytes = await upload.read()

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw_bytes)
            tmp_path = Path(tmp.name)

        # Convert bytes → Markdown on the server (full markitdown pipeline).
        # Use asyncio.to_thread because _convert is a blocking call.
        import asyncio

        markdown = await asyncio.to_thread(_convert, tmp_path)
    except UnsupportedFormatError as e:
        return JSONResponse(
            {"status": "error", "error": f"Unsupported format: {e}"}, status_code=422
        )
    except Exception as e:
        logger.exception("Unexpected error converting upload")
        return JSONResponse(
            {"status": "error", "error": f"Conversion failed: {e}"}, status_code=500
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    # Ingest the converted Markdown using the original filename as source so that
    # dedup and the index label use the real name, not the temp path.
    try:
        result = await _ingest_content(
            content=markdown,
            source=filename,
            library=library,
            metadata=metadata,
            store=_store,
        )
        return JSONResponse(result.model_dump())
    except IngestionError as e:
        return JSONResponse(
            {"status": "error", "error": f"Ingestion failed: {e}"}, status_code=500
        )
    except Exception as e:
        logger.exception("Unexpected error in upload_handler")
        return JSONResponse(
            {"status": "error", "error": f"Internal error: {e}"}, status_code=500
        )


# ── OAuth Protected Resource Metadata ─────────────────────────────────────────
@mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
async def oauth_protected_resource(request: Request) -> JSONResponse:
    """RFC 9728 Protected Resource Metadata — tells clients to use Google as the AS.

    Always public (no authentication required). Registers this server as a
    resource protected by Google's authorization server.
    """
    resource_url = settings.oauth_resource_url or str(request.base_url).rstrip("/")
    return JSONResponse(
        {
            "resource": resource_url,
            "authorization_servers": ["https://accounts.google.com"],
            "bearer_methods_supported": ["header"],
            "scopes_supported": ["openid", "email"],
        }
    )


# ── OAuth enforcement middleware ───────────────────────────────────────────────
class _RequireGoogleAuth:
    """Enforce authentication on all paths except /.well-known/*.

    Must be added as the inner middleware (after AuthenticationMiddleware) so
    that scope["user"] is populated before this check runs.
    """

    _EXCLUDED_PREFIX = "/.well-known/"

    def __init__(self, app: Any) -> None:
        """Initialise with the inner ASGI application."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass through /.well-known/* requests; enforce auth on all others."""
        if scope["type"] == "http":
            path = scope.get("path", "")
            if not path.startswith(self._EXCLUDED_PREFIX):
                user = scope.get("user")
                if not getattr(user, "is_authenticated", False):
                    await self._send_401(send)
                    return
        await self.app(scope, receive, send)

    @staticmethod
    async def _send_401(send: Send) -> None:
        """Send a 401 Unauthorized JSON response."""
        body = json.dumps(
            {
                "error": "invalid_token",
                "error_description": "Authentication required",
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b'Bearer realm="mcpvectordb"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


# ── TLS validation ────────────────────────────────────────────────────────────
def _validate_tls_config() -> None:
    """Raise ValueError or log a warning if TLS settings are inconsistent."""
    if not settings.tls_enabled:
        return
    if settings.mcp_transport == "stdio":
        logger.warning(
            "TLS_ENABLED=true has no effect with MCP_TRANSPORT=stdio; "
            "TLS only applies to streamable-http."
        )
        return
    if settings.mcp_transport != "streamable-http":
        logger.warning(
            "TLS_ENABLED=true is not supported with MCP_TRANSPORT=%s; "
            "use a reverse proxy for TLS with SSE transport.",
            settings.mcp_transport,
        )
        return
    missing = [
        v
        for v, val in (
            ("TLS_CERT_FILE", settings.tls_cert_file),
            ("TLS_KEY_FILE", settings.tls_key_file),
        )
        if not val
    ]
    if missing:
        raise ValueError(f"TLS_ENABLED=true but missing: {', '.join(missing)}")
    for label, path_str in (
        ("TLS_CERT_FILE", settings.tls_cert_file),
        ("TLS_KEY_FILE", settings.tls_key_file),
    ):
        p = Path(path_str).expanduser().resolve()  # type: ignore[arg-type]
        if not p.exists():
            raise ValueError(f"{label} not found: {p}")


# ── OAuth validation ──────────────────────────────────────────────────────────
def _validate_oauth_config() -> None:
    """Log a warning or raise ValueError if OAuth settings are inconsistent."""
    if not settings.oauth_enabled:
        return
    if settings.mcp_transport == "stdio":
        logger.warning(
            "OAUTH_ENABLED=true has no effect with MCP_TRANSPORT=stdio; "
            "OAuth only applies to streamable-http."
        )
        return
    if not settings.oauth_client_id:
        raise ValueError("OAUTH_ENABLED=true requires OAUTH_CLIENT_ID to be set")


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    """Start the MCP server with the configured transport."""
    import os

    # PyInstaller frozen bundle: use bundled model cache unless user overrides.
    # sys.frozen is set by PyInstaller's bootloader; sys._MEIPASS is the
    # temp directory where the bundle is extracted at runtime.
    if getattr(sys, "frozen", False) and not os.environ.get("FASTEMBED_CACHE_PATH"):
        _bundle = Path(getattr(sys, "_MEIPASS", ""))
        os.environ["FASTEMBED_CACHE_PATH"] = str(_bundle / "fastembed_cache")

    _validate_tls_config()
    _validate_oauth_config()
    logger.info("mcpvectordb starting (transport=%s)", settings.mcp_transport)

    # Ensure runtime data directories exist before any I/O
    Path(settings.lancedb_uri).expanduser().mkdir(parents=True, exist_ok=True)
    if settings.log_file:
        Path(settings.log_file).expanduser().parent.mkdir(parents=True, exist_ok=True)
    if settings.fastembed_cache_path:
        cache_path = Path(settings.fastembed_cache_path).expanduser()
        cache_path.mkdir(parents=True, exist_ok=True)
        os.environ["FASTEMBED_CACHE_PATH"] = str(cache_path)

    # Pre-warm embedder at startup to avoid first-call latency
    logger.info("Pre-loading embedding model %s", settings.embedding_model)
    get_embedder()
    logger.info("Embedding model loaded. Ready.")

    if settings.mcp_transport == "stdio":
        mcp.run(transport="stdio")
    elif settings.mcp_transport == "streamable-http":
        import asyncio

        import uvicorn

        async def _serve() -> None:
            app = mcp.streamable_http_app()

            if settings.oauth_enabled:
                from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
                from starlette.middleware.authentication import AuthenticationMiddleware

                from mcpvectordb.auth import GoogleTokenVerifier

                verifier = GoogleTokenVerifier(
                    client_id=settings.oauth_client_id,  # type: ignore[arg-type]
                    allowed_emails=settings.oauth_allowed_emails_list,
                )
                # Add _RequireGoogleAuth first (innermost) so it runs after
                # AuthenticationMiddleware has populated scope["user"].
                app.add_middleware(_RequireGoogleAuth)
                app.add_middleware(AuthenticationMiddleware, backend=BearerAuthBackend(verifier))

            ssl_certfile: str | None = None
            ssl_keyfile: str | None = None
            if settings.tls_enabled:
                ssl_certfile = str(
                    Path(settings.tls_cert_file).expanduser().resolve()  # type: ignore[arg-type]
                )
                ssl_keyfile = str(
                    Path(settings.tls_key_file).expanduser().resolve()  # type: ignore[arg-type]
                )
            config = uvicorn.Config(
                app,
                host=settings.mcp_host,
                port=settings.mcp_port,
                log_level=settings.log_level.lower(),
                # Accept forwarded requests from reverse proxies (tailscale serve,
                # nginx, etc.) whose Host header differs from the bind address.
                proxy_headers=True,
                forwarded_allow_ips="*",
                ssl_certfile=ssl_certfile,
                ssl_keyfile=ssl_keyfile,
            )
            await uvicorn.Server(config).serve()

        asyncio.run(_serve())
    else:
        mcp.run(transport="sse")


if __name__ == "__main__":  # pragma: no cover
    main()
