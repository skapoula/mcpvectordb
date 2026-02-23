#Requires -Version 5.1
<#
.SYNOPSIS
    Build mcpvectordb.exe — a self-contained Windows executable for Claude Desktop.

.DESCRIPTION
    Performs a three-step build:
      1. Installs all Python dependencies (uv sync --all-groups)
      2. Downloads the embedding model (~500 MB ONNX) to build_models/
      3. Runs PyInstaller to produce dist\mcpvectordb.exe (~800 MB–1 GB)

    The resulting .exe contains everything:
      - mcpvectordb MCP server and all Python dependencies
      - LanceDB vector store with full-text search (tantivy)
      - nomic-embed-text-v1.5 ONNX embedding model
      - MarkItDown converters for PDF, Word, PowerPoint, Excel, HTML

    No Python installation required on the target Windows machine.
    No network access required after initial setup.

.NOTES
    Run from the mcpvectordb project root:
        .\scripts\build-windows.ps1

    Pre-requisites:
        uv   (https://docs.astral.sh/uv/) — for dependency management
        The model download requires ~500 MB of disk space.
        The final .exe requires ~800 MB–1 GB of disk space.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Helpers ────────────────────────────────────────────────────────────────────

function Write-Step { param([string]$Msg) Write-Host "`n>>> $Msg" -ForegroundColor Cyan }
function Write-OK   { param([string]$Msg) Write-Host "    OK  $Msg" -ForegroundColor Green }
function Write-Fail { param([string]$Msg) Write-Host "    FAIL $Msg" -ForegroundColor Red; exit 1 }

# ── Paths ──────────────────────────────────────────────────────────────────────

$ProjectDir  = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$BuildModels = Join-Path $ProjectDir "build_models"
$DistDir     = Join-Path $ProjectDir "dist"
$ExePath     = Join-Path $DistDir "mcpvectordb.exe"

Set-Location $ProjectDir

# ── Step 1: Install all dependencies (including pyinstaller) ──────────────────

Write-Step "Installing dependencies (uv sync --python 3.13 --all-groups)…"
uv sync --python 3.13 --all-groups
if ($LASTEXITCODE -ne 0) { Write-Fail "uv sync failed" }
Write-OK "Dependencies installed"

# ── Step 2: Download the embedding model ──────────────────────────────────────

Write-Step "Downloading embedding model to build_models/…"
Write-Host "    (nomic-embed-text-v1.5, ~500 MB — skip with Ctrl+C if already done)"

$env:FASTEMBED_CACHE_PATH = $BuildModels
uv run mcpvectordb-download-model
if ($LASTEXITCODE -ne 0) { Write-Fail "Model download failed" }
Write-OK "Model ready in $BuildModels"

# ── Step 3: Run PyInstaller ───────────────────────────────────────────────────

Write-Step "Building .exe with PyInstaller…"
Write-Host "    This takes several minutes. Output: $ExePath"

uv run pyinstaller mcpvectordb.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { Write-Fail "PyInstaller build failed" }
Write-OK "Build complete"

# ── Step 4: Print success and Claude Desktop config ───────────────────────────

$ExeSizeMB = [math]::Round((Get-Item $ExePath).Length / 1MB, 0)

Write-Host ""
Write-Host "=== Build succeeded ===" -ForegroundColor Green
Write-Host ""
Write-Host "  Executable : $ExePath  ($ExeSizeMB MB)" -ForegroundColor White
Write-Host ""
Write-Host "  Add this to %APPDATA%\Claude\claude_desktop_config.json:" -ForegroundColor Yellow
Write-Host ""

$ExeJson = $ExePath -replace "\\", "\\"

Write-Host @"
{
  "mcpServers": {
    "mcpvectordb": {
      "command": "$ExeJson",
      "args": [],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "LANCEDB_URI": "C:\\Users\\<you>\\AppData\\Local\\mcpvectordb\\lancedb",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
"@ -ForegroundColor White

Write-Host ""
Write-Host "  The exe uses the bundled embedding model — no download on first run." -ForegroundColor Green
Write-Host "  LanceDB data is stored separately in LANCEDB_URI." -ForegroundColor Green
Write-Host ""
Write-Host "Restart Claude Desktop after updating the config." -ForegroundColor Cyan
