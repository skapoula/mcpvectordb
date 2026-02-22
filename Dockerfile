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

COPY pyproject.toml ./
COPY src/ ./src/

RUN uv pip install --system .

# ── Embedding model (baked into the image) ────────────────────────────────────
# Download the ONNX model at build time so the container starts instantly with
# no network access required at runtime. Override EMBEDDING_MODEL if you change
# the model in config.py (must match EMBEDDING_MODEL in your .env).
ARG EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5

RUN FASTEMBED_CACHE_PATH=/opt/models python -c \
    "from fastembed import TextEmbedding; TextEmbedding(model_name='${EMBEDDING_MODEL}')" \
    && echo "Model baked in at /opt/models"

# ── Volumes ───────────────────────────────────────────────────────────────────
# /data/lancedb — vector store (Docker named volume or k3s PVC)
# /data/docs    — source documents for ingest_file (bind-mount, read-only)
# No model-cache volume — the ONNX model is baked into the image at /opt/models.
VOLUME ["/data/lancedb", "/data/docs"]

# ── Runtime environment ───────────────────────────────────────────────────────
# All values are overridable via --env / environment: in Compose / k3s.
ENV MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    LANCEDB_URI=/data/lancedb \
    FASTEMBED_CACHE_PATH=/opt/models

EXPOSE 8000

# ── Health check ─────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# ── Entry point ───────────────────────────────────────────────────────────────
ENTRYPOINT ["mcpvectordb"]
