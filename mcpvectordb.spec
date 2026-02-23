# -*- mode: python ; coding: utf-8 -*-
#
# mcpvectordb.spec — PyInstaller build spec for Windows 11 native .exe
#
# Produces a single-file executable that bundles:
#   • The complete mcpvectordb MCP server
#   • All Python dependencies (lancedb, fastembed, mcp, markitdown, …)
#   • The ONNX embedding model (nomic-embed-text-v1.5, ~500 MB)
#
# Pre-requisites (run build-windows.ps1 instead of running this directly):
#   1. uv sync --all-groups           — install all dependencies incl. pyinstaller
#   2. FASTEMBED_CACHE_PATH=build_models uv run mcpvectordb-download-model
#                                     — download model to build_models/ staging dir
#   3. uv run pyinstaller mcpvectordb.spec --noconfirm
#
# Output: dist\mcpvectordb.exe  (~800 MB–1 GB depending on optional deps)
#
# Claude Desktop config (claude_desktop_config.json):
#   {
#     "mcpServers": {
#       "mcpvectordb": {
#         "command": "C:\\path\\to\\mcpvectordb.exe",
#         "args": [],
#         "env": {
#           "MCP_TRANSPORT": "stdio",
#           "LANCEDB_URI": "C:\\Users\\<you>\\AppData\\Local\\mcpvectordb\\lancedb"
#         }
#       }
#     }
#   }

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# ── Project root (spec file lives here) ───────────────────────────────────────
PROJECT_ROOT = Path(SPECPATH)  # noqa: F821 — SPECPATH is set by PyInstaller
SRC = PROJECT_ROOT / "src"

# ── Collect complex packages that use dynamic imports ─────────────────────────
datas = []
binaries = []
hiddenimports = []

for pkg in [
    "lancedb",
    "lance",
    "fastembed",
    "onnxruntime",
    "tokenizers",
    "mcp",
    "markitdown",
    "pydantic",
    "pydantic_settings",
    "pyarrow",
    "starlette",
    "anyio",
    "httpx",
]:
    try:
        tmp = collect_all(pkg)
        datas += tmp[0]
        binaries += tmp[1]
        hiddenimports += tmp[2]
    except Exception:
        pass  # package may not be installed; skip rather than fail the build

# Tantivy is lancedb's full-text search backend — binary extension
try:
    hiddenimports += collect_submodules("tantivy")
except Exception:
    pass

# ── Bundle the pre-downloaded embedding model ─────────────────────────────────
# build_models/ must exist before running pyinstaller (populated by build script).
# At runtime, server.py sets FASTEMBED_CACHE_PATH = sys._MEIPASS/fastembed_cache
MODEL_STAGING = PROJECT_ROOT / "build_models"
if MODEL_STAGING.exists():
    datas += [(str(MODEL_STAGING), "fastembed_cache")]
else:
    import warnings
    warnings.warn(
        "build_models/ directory not found — embedding model will NOT be bundled. "
        "Run: FASTEMBED_CACHE_PATH=build_models uv run mcpvectordb-download-model",
        stacklevel=1,
    )

# ── Additional hidden imports for dynamic-import patterns ─────────────────────
hiddenimports += [
    # mcpvectordb internals
    "mcpvectordb.server",
    "mcpvectordb.config",
    "mcpvectordb.ingestor",
    "mcpvectordb.converter",
    "mcpvectordb.chunker",
    "mcpvectordb.embedder",
    "mcpvectordb.store",
    "mcpvectordb.exceptions",
    "mcpvectordb.auth",
    "mcpvectordb._download_model",
    # markitdown optional parsers (imported lazily by extension)
    "markitdown._markitdown",
    "pdfminer",
    "pdfminer.high_level",
    "docx",
    "openpyxl",
    "pptx",
    "bs4",
    "charset_normalizer",
    # pyarrow IPC and compute modules (used by lancedb)
    "pyarrow.lib",
    "pyarrow.compute",
    "pyarrow._compute",
    "pyarrow.ipc",
    "pyarrow.gandiva",
    # onnxruntime providers
    "onnxruntime.capi.onnxruntime_inference_collection",
    # asyncio / event loop helpers
    "asyncio",
    "asyncio.selector_events",
    "asyncio.proactor_events",  # Windows event loop
    # encoding
    "encodings.utf_8",
    "encodings.ascii",
    "encodings.latin_1",
]

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(SRC / "mcpvectordb" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy ML frameworks not needed at runtime
        "torch",
        "tensorflow",
        "jax",
        "sklearn",
        "scipy",
        "matplotlib",
        "IPython",
        "jupyter",
        "notebook",
        # Test infrastructure
        "pytest",
        "hypothesis",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)  # noqa: F821 — PYZ is PyInstaller built-in

# ── Single-file exe ───────────────────────────────────────────────────────────
exe = EXE(  # noqa: F821 — EXE is PyInstaller built-in
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="mcpvectordb",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,        # compress with UPX if available (reduces size by ~30%)
    upx_exclude=[],
    runtime_tmpdir=None,
    # console=True keeps stdin/stdout open for MCP stdio transport.
    # Claude Desktop spawns the exe as a subprocess and communicates over
    # stdin/stdout; a console window will not be visible to the user.
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,         # set to a .ico path to add a custom icon
    version=None,      # set to a version_info.txt for Windows file properties
)
