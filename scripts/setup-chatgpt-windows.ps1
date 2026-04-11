#Requires -Version 5.1
<#
.SYNOPSIS
    Bootstrap mcpvectordb for native Windows 11 use with ChatGPT Desktop (SSE transport).

.DESCRIPTION
    Checks prerequisites, installs Python dependencies, creates data directories,
    generates a .env file configured for SSE transport, downloads NSSM, installs
    mcpvectordb as a Windows background service, and prints the URL to paste into
    ChatGPT Desktop's Developer Mode settings.

.NOTES
    Must be run as Administrator (Windows service installation requires elevation).

    Run from the mcpvectordb project root:
        .\scripts\setup-chatgpt-windows.ps1

    Requires: uv (https://docs.astral.sh/uv/), Python 3.11+, ChatGPT Desktop for Windows.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Helpers ────────────────────────────────────────────────────────────────────

function Write-Step { param([string]$Message) Write-Host "`n>>> $Message" -ForegroundColor Cyan }
function Write-OK   { param([string]$Message) Write-Host "    OK  $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "    WARN $Message" -ForegroundColor Yellow }
function Write-Fail { param([string]$Message) Write-Host "    FAIL $Message" -ForegroundColor Red; exit 1 }

# ── Step 0: Require Administrator ─────────────────────────────────────────────
# Windows service installation always requires elevation.

Write-Step "Checking for Administrator privileges..."
$currentPrincipal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host ""
    Write-Host "  This script must be run as Administrator." -ForegroundColor Red
    Write-Host "  Right-click PowerShell and choose 'Run as Administrator'." -ForegroundColor Yellow
    exit 1
}
Write-OK "Running as Administrator"

# ── Step 1: Check uv ──────────────────────────────────────────────────────────

Write-Step "Checking for uv..."
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "  uv is not installed or not on PATH." -ForegroundColor Red
    Write-Host "  Install it with:" -ForegroundColor Yellow
    Write-Host "      irm https://astral.sh/uv/install.ps1 | iex" -ForegroundColor White
    Write-Host "  Then open a new terminal (as Administrator) and re-run this script." -ForegroundColor Yellow
    exit 1
}
$uvVersion = (uv --version) -replace "uv ", ""
Write-OK "uv $uvVersion found"

# ── Step 2: Ensure Python 3.13 is available ───────────────────────────────────

# onnxruntime (required by fastembed) does not yet publish wheels for Python 3.14+.
# We pin to 3.13 explicitly so uv never picks a newer system Python by accident.
Write-Step "Ensuring Python 3.13 is available via uv..."
$py313Ok = $false
try {
    $pyOutput = uv python list 2>&1
    if ($pyOutput -match "3\.13") {
        $py313Ok = $true
        Write-OK "Python 3.13 already available"
    }
} catch {}

if (-not $py313Ok) {
    Write-Host "    Installing Python 3.13 via uv (one-time download)..." -ForegroundColor Yellow
    uv python install 3.13
    if ($LASTEXITCODE -ne 0) { Write-Fail "Failed to install Python 3.13" }
    Write-OK "Python 3.13 installed"
}

# ── Step 3: Install Python dependencies ───────────────────────────────────────

Write-Step "Installing Python dependencies (uv sync --python 3.13)..."
uv sync --python 3.13
if ($LASTEXITCODE -ne 0) { Write-Fail "uv sync failed" }
Write-OK "Dependencies installed"

# ── Step 4: Download embedding model ──────────────────────────────────────────

Write-Step "Downloading embedding model (nomic-embed-text-v1.5, ~500 MB)..."
Write-Host "    This is a one-time download. Skip with Ctrl+C if already done." -ForegroundColor Yellow
uv run mcpvectordb-download-model
if ($LASTEXITCODE -ne 0) { Write-Warn "Model download failed — server will re-attempt on first run." }
else { Write-OK "Embedding model ready" }

# ── Step 5: Create data directories ───────────────────────────────────────────

Write-Step "Creating data directories..."

$DataDir   = Join-Path $env:LOCALAPPDATA "mcpvectordb"
$LanceDir  = Join-Path $DataDir "lancedb"
$ModelsDir = Join-Path $DataDir "models"
$LogFile   = Join-Path $DataDir "chatgpt-service.log"

foreach ($Dir in @($LanceDir, $ModelsDir)) {
    if (-not (Test-Path $Dir)) {
        New-Item -ItemType Directory -Path $Dir -Force | Out-Null
        Write-OK "Created $Dir"
    } else {
        Write-OK "Already exists: $Dir"
    }
}

# ── Step 6: Generate .env ─────────────────────────────────────────────────────

Write-Step "Generating .env..."

$EnvFile = Join-Path $PSScriptRoot ".." ".env"
$EnvFile = [System.IO.Path]::GetFullPath($EnvFile)

if (Test-Path $EnvFile) {
    # Check if existing .env has the wrong transport
    $envContent = Get-Content $EnvFile -Raw
    if ($envContent -match "MCP_TRANSPORT=stdio") {
        Write-Warn ".env exists with MCP_TRANSPORT=stdio — the ChatGPT service needs MCP_TRANSPORT=sse."
        Write-Warn "Edit .env and change MCP_TRANSPORT=stdio to MCP_TRANSPORT=sse, then re-run this script."
        exit 1
    }
    Write-Warn ".env already exists — skipping generation (delete it to regenerate)"
} else {
    $EnvContent = @"
# mcpvectordb — Windows 11 ChatGPT Desktop configuration
# Generated by scripts\setup-chatgpt-windows.ps1
# Edit as needed; never commit this file.

MCP_TRANSPORT=sse
MCP_HOST=127.0.0.1
MCP_PORT=8000

LANCEDB_URI=$LanceDir
FASTEMBED_CACHE_PATH=$ModelsDir

LOG_LEVEL=INFO
"@
    Set-Content -Path $EnvFile -Value $EnvContent -Encoding UTF8
    Write-OK "Created .env at $EnvFile"
}

# ── Step 7: Check port availability ───────────────────────────────────────────

# Read MCP_PORT from .env if it already exists, otherwise default to 8000
$McpPort = 8000
if (Test-Path $EnvFile) {
    $envLines = Get-Content $EnvFile -ErrorAction SilentlyContinue
    $portLine = $envLines | Where-Object { $_ -match "^MCP_PORT\s*=\s*(\d+)" }
    if ($portLine -and $Matches[1]) { $McpPort = [int]$Matches[1] }
}

Write-Step "Checking port $McpPort..."
$portInUse = netstat -ano | Select-String "[:.]$McpPort\s"
if ($portInUse) {
    Write-Warn "Port $McpPort is already in use. Set MCP_PORT to a free port in .env and re-run."
    Write-Warn "Processes using port ${McpPort}:"
    $portInUse | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
    exit 1
}
Write-OK "Port $McpPort is free"

# ── Step 8: Download NSSM ─────────────────────────────────────────────────────

Write-Step "Downloading NSSM (Windows service manager)..."

$NssmDir = Join-Path $PSScriptRoot "nssm"
$NssmExe = Join-Path $NssmDir "nssm.exe"

if (Test-Path $NssmExe) {
    Write-OK "NSSM already present at $NssmExe"
} else {
    $NssmZip = Join-Path $env:TEMP "nssm-2.24.zip"
    $NssmUrl = "https://nssm.cc/release/nssm-2.24.zip"

    try {
        Write-Host "    Downloading from $NssmUrl ..." -ForegroundColor Yellow
        Invoke-WebRequest -Uri $NssmUrl -OutFile $NssmZip -UseBasicParsing
    } catch {
        Write-Host ""
        Write-Host "  NSSM download failed. Download manually from https://nssm.cc/download" -ForegroundColor Red
        Write-Host "  Extract nssm-2.24\win64\nssm.exe to scripts\nssm\nssm.exe, then re-run." -ForegroundColor Yellow
        exit 1
    }

    # Extract win64\nssm.exe
    if (-not (Test-Path $NssmDir)) { New-Item -ItemType Directory -Path $NssmDir -Force | Out-Null }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($NssmZip)
    $entry = $zip.Entries | Where-Object { ($_.FullName -replace '\\', '/') -eq "nssm-2.24/win64/nssm.exe" }
    if (-not $entry) { $zip.Dispose(); Write-Fail "Could not find nssm.exe in zip archive" }
    [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $NssmExe, $true)
    $zip.Dispose()
    Remove-Item $NssmZip -Force
    Write-OK "NSSM extracted to $NssmExe"
}

# ── Step 9: Install Windows service ───────────────────────────────────────────

Write-Step "Installing mcpvectordb-chatgpt Windows service..."

$ServiceName = "mcpvectordb-chatgpt"
$ProjectDir  = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$UvPath      = (Get-Command uv).Source

# Remove existing service if present (idempotent re-run)
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Warn "Service '$ServiceName' already exists — removing and reinstalling..."
    try { & $NssmExe stop $ServiceName 2>&1 | Out-Null } catch {}
    Start-Sleep -Seconds 2
    & $NssmExe remove $ServiceName confirm
    if ($LASTEXITCODE -ne 0) { Write-Fail "Failed to remove existing service '$ServiceName'. Stop it manually and re-run." }
    Write-OK "Existing service removed"
}

# Install service
& $NssmExe install $ServiceName $UvPath "run" "--directory" $ProjectDir "mcpvectordb"
if ($LASTEXITCODE -ne 0) { Write-Fail "nssm install failed" }

# Configure environment variables (passed directly to the service process)
& $NssmExe set $ServiceName AppEnvironmentExtra `
    "MCP_TRANSPORT=sse" `
    "MCP_HOST=127.0.0.1" `
    "MCP_PORT=$McpPort" `
    "LANCEDB_URI=$LanceDir" `
    "FASTEMBED_CACHE_PATH=$ModelsDir" `
    "LOG_LEVEL=INFO"

# Redirect stdout/stderr to log file
& $NssmExe set $ServiceName AppStdout $LogFile
& $NssmExe set $ServiceName AppStderr $LogFile
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateBytes 10485760  # 10 MB

# Start automatically at login
& $NssmExe set $ServiceName Start SERVICE_AUTO_START

Write-OK "Service '$ServiceName' installed"
Write-Warn "The service runs as SYSTEM. On domain-joined machines verify SYSTEM has read/write access to $DataDir"

# ── Step 10: Start service ─────────────────────────────────────────────────────

Write-Step "Starting service..."
& $NssmExe start $ServiceName
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Service failed to start immediately. Check logs at: $LogFile"
} else {
    Write-OK "Service started"
}

# ── Step 11: Print URL and instructions ───────────────────────────────────────

Write-Host ""
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  mcpvectordb is now running as a Windows service." -ForegroundColor White
Write-Host "  It will start automatically at every login." -ForegroundColor White
Write-Host ""
Write-Host "  Paste this URL into ChatGPT Desktop:" -ForegroundColor Yellow
Write-Host "  Settings → Apps → Advanced settings → Developer mode" -ForegroundColor Yellow
Write-Host ""
Write-Host "      http://127.0.0.1:${McpPort}/sse" -ForegroundColor White
Write-Host ""
Write-Host "  Then open a new ChatGPT conversation and ask:" -ForegroundColor Cyan
Write-Host "      'List all libraries'" -ForegroundColor White
Write-Host "  to confirm the server is connected." -ForegroundColor Cyan
Write-Host ""
Write-Host "  Service log: $LogFile" -ForegroundColor DarkGray
Write-Host "  To uninstall: .\scripts\uninstall-chatgpt-windows.ps1" -ForegroundColor DarkGray
Write-Host ""
