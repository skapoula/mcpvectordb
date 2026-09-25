# shellcheck shell=bash
# Shared helpers for the Linux setup scripts. Sourced, not executed.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# config.py's non-Windows default. The model download and the service read the
# same settings (.env or this default), so the model lands where the server looks.
DATA_DIR="$HOME/.mcpvectordb"
LANCE_DIR="$DATA_DIR/lancedb"
MODELS_DIR="$DATA_DIR/models"
ENV_FILE="$PROJECT_DIR/.env"

step() { printf '\n\033[36m>>> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[32mOK\033[0m  %s\n' "$1"; }
warn() { printf '    \033[33mWARN\033[0m %s\n' "$1"; }
fail() { printf '    \033[31mFAIL\033[0m %s\n' "$1"; exit 1; }

# uv check, dependency install, model pre-download, data directories.
install_base() {
    step "Checking for uv..."
    if ! command -v uv >/dev/null; then
        printf '  uv is not installed or not on PATH. Install it with:\n'
        printf '      curl -LsSf https://astral.sh/uv/install.sh | sh\n'
        fail "then open a new shell and re-run this script."
    fi
    ok "$(uv --version) found"

    # requires-python = ">=3.11,<3.14" in pyproject.toml keeps uv off 3.14
    # (no onnxruntime wheel yet); uv downloads a matching Python if none exists.
    step "Installing Python dependencies (uv sync)..."
    (cd "$PROJECT_DIR" && uv sync) || fail "uv sync failed"
    ok "Dependencies installed"

    step "Creating data directories..."
    mkdir -p "$LANCE_DIR" "$MODELS_DIR"
    ok "$DATA_DIR"

    step "Downloading embedding model (nomic-embed-text-v1.5, ~500 MB, one-time)..."
    if (cd "$PROJECT_DIR" && uv run mcpvectordb-download-model); then
        ok "Embedding model ready"
    else
        warn "Model download failed — server will re-attempt on first run."
    fi
}
