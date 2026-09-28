FROM python:3.11-slim-bookworm

# ── System packages ──────────────────────────────────────────────────────────
# MEDIA_FORMATS=true adds ffmpeg (audio transcription) and tesseract-ocr (image
# OCR) via markitdown[all]. Omit for a ~100 MB slimmer image; those two ingest
# formats simply return UnsupportedFormatError at runtime.
#   Full:  podman build --build-arg MEDIA_FORMATS=true -t mcpvectordb:0.1.0-full .
#   Slim:  podman build -t mcpvectordb:0.1.0 .          (default)
ARG MEDIA_FORMATS=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libmagic1 \
        libmagic-dev \
        curl \
    && if [ "$MEDIA_FORMATS" = "true" ]; then \
         apt-get install -y --no-install-recommends ffmpeg tesseract-ocr; \
       fi \
    && rm -rf /var/lib/apt/lists/*

# ── uv ───────────────────────────────────────────────────────────────────────
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ── Project ───────────────────────────────────────────────────────────────────
# fastembed uses ONNX Runtime instead of PyTorch — no torch pre-install needed.
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ ./src/

RUN uv sync --frozen --no-dev --python /usr/local/bin/python
ENV PATH="/app/.venv/bin:$PATH"

# ── Embedding model (baked into the image) ────────────────────────────────────
# Download the ONNX model at build time so the container starts instantly with
# no network access required at runtime. Override EMBEDDING_MODEL if you change
# the model in config.py (must match EMBEDDING_MODEL in your .env).
ARG EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5

# The chunker's tokenizer is required at startup too; it goes to HF_HOME.
RUN FASTEMBED_CACHE_PATH=/opt/models HF_HOME=/opt/models/hf \
    EMBEDDING_MODEL=${EMBEDDING_MODEL} mcpvectordb-download-model

# ── Volumes ───────────────────────────────────────────────────────────────────
# /data/lancedb — vector store (Docker named volume or k3s PVC)
# /data/docs    — source documents for ingest_file (bind-mount, read-only)
# /certs        — read-only bind mount for TLS cert+key (Mode D / TLS_ENABLED=true only).
#                 Mount with: -v ./certs:/certs:ro  or via compose Mode D volume block.
# No model-cache volume — the ONNX model and tokenizer are baked in at /opt/models.
VOLUME ["/data/lancedb", "/data/docs"]

# ── Runtime environment ───────────────────────────────────────────────────────
# All values are overridable via --env / environment: in Compose / k3s.
ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    LANCEDB_URI=/data/lancedb \
    FASTEMBED_CACHE_PATH=/opt/models \
    HF_HOME=/opt/models/hf

EXPOSE 8000

# ── Health check ─────────────────────────────────────────────────────────────
# TCP connect, not HTTP: there is no route at / and /mcp needs MCP headers (and a
# token with OAUTH_ENABLED, TLS with TLS_ENABLED). The port only opens after both
# models are loaded, so an open port means ready.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os, socket; socket.create_connection(('localhost', int(os.environ.get('MCP_PORT', 8000))), 5)"

# ── Entry point ───────────────────────────────────────────────────────────────
ENTRYPOINT ["mcpvectordb"]
