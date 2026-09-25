#!/usr/bin/env bash
# Build dist/mcpvectordb — a self-contained Linux executable (no Python needed on the
# target) bundling the server, all dependencies and the embedding model.
# Linux counterpart of scripts/build-windows.ps1; uses the same mcpvectordb.spec.
#
# The binary links against the build machine's glibc: build on the oldest distro
# you intend to run it on.
set -euo pipefail
# shellcheck source=scripts/_common-linux.sh
source "$(dirname "$0")/_common-linux.sh"

cd "$PROJECT_DIR"

step "Installing dependencies (uv sync --all-groups)..."
uv sync --all-groups || fail "uv sync failed"
ok "Dependencies installed"

step "Downloading embedding model to build_models/..."
FASTEMBED_CACHE_PATH="$PROJECT_DIR/build_models" uv run mcpvectordb-download-model \
    || fail "Model download failed"
ok "Model ready in build_models/"

step "Building binary with PyInstaller (several minutes)..."
uv run pyinstaller mcpvectordb.spec --noconfirm --distpath dist --workpath build \
    || fail "PyInstaller build failed"

BIN="$PROJECT_DIR/dist/mcpvectordb"
cat <<EOF

=== Build succeeded ===

  Executable: $BIN ($(du -h "$BIN" | cut -f1))

  Claude Desktop (~/.config/Claude/claude_desktop_config.json):

{
  "mcpServers": {
    "mcpvectordb": {
      "command": "$BIN",
      "args": [],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "LANCEDB_URI": "$LANCE_DIR",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}

  Claude Code:  claude mcp add mcpvectordb --scope user -- "$BIN"

  The binary uses the bundled embedding model — no download on first run.
EOF
