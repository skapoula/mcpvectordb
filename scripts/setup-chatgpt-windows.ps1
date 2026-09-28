#Requires -Version 5.1
<#
.SYNOPSIS
    Bootstrap mcpvectordb for native Windows 11 use with ChatGPT Desktop (streamable-http transport).

.DESCRIPTION
    Checks prerequisites, installs Python dependencies, creates data directories,
    generates a .env file configured for streamable-http transport, downloads servy-cli,
    installs mcpvectordb as a Windows background service, and prints instructions for
    exposing the server via Tailscale serve for use with ChatGPT Desktop.

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

# ── Step 4: Create data directories ───────────────────────────────────────────

Write-Step "Creating data directories..."

# Use ProgramData (C:\ProgramData\mcpvectordb) so the SYSTEM account that runs
# the Windows service can read the LanceDB index and the embedding model cache.
# LOCALAPPDATA is user-specific and not accessible to SYSTEM.
$DataDir   = Join-Path $env:ProgramData "mcpvectordb"
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

# ── Step 5: Download embedding model ──────────────────────────────────────────
# Into the ProgramData cache the service reads. Without these variables the
# download lands in this user's default cache, where the SYSTEM service never
# looks, and the service fails to start for lack of the tokenizer.

Write-Step "Downloading embedding model and tokenizer (nomic-embed-text-v1.5, ~600 MB)..."
Write-Host "    This is a one-time download; cached files are reused on later runs." -ForegroundColor Yellow
$env:FASTEMBED_CACHE_PATH = $ModelsDir
$env:HF_HOME = $ModelsDir
uv run mcpvectordb-download-model
if ($LASTEXITCODE -ne 0) { Write-Fail "Model download failed. The service needs this cache to start." }
Write-OK "Embedding model ready in $ModelsDir"

# ── Step 6: Generate .env ─────────────────────────────────────────────────────

Write-Step "Generating .env..."

$EnvFile = Join-Path (Join-Path $PSScriptRoot "..") ".env"
$EnvFile = [System.IO.Path]::GetFullPath($EnvFile)

if (Test-Path $EnvFile) {
    # Service variables below take precedence over .env, so an existing stdio
    # configuration for another client can coexist with this service.
    Write-Warn ".env already exists — keeping it. Service transport and data paths are set separately."
} else {
    $EnvContent = @"
# mcpvectordb — Windows 11 ChatGPT Desktop configuration
# Generated by scripts\setup-chatgpt-windows.ps1
# Edit as needed; never commit this file.

MCP_TRANSPORT=streamable-http
MCP_HOST=127.0.0.1
MCP_PORT=8000

LANCEDB_URI=$LanceDir
FASTEMBED_CACHE_PATH=$ModelsDir
HF_HOME=$ModelsDir

LOG_LEVEL=INFO
"@
    Set-Content -Path $EnvFile -Value $EnvContent -Encoding UTF8
    Write-OK "Created .env at $EnvFile"
}

# ── Step 7: Check port availability ───────────────────────────────────────────

# Read MCP_PORT from .env if it already exists, otherwise default to 8000
$McpPort = 8000
if (Test-Path $EnvFile) {
    foreach ($line in (Get-Content $EnvFile)) {
        if ($line -match '^MCP_PORT\s*=\s*(\d+)') {
            $McpPort = [int]$Matches[1]
        }
    }
}
if ($McpPort -lt 1 -or $McpPort -gt 65535) { Write-Fail "MCP_PORT must be between 1 and 65535." }

Write-Step "Checking port $McpPort..."
$ServiceName = "mcpvectordb-chatgpt"
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    # The existing installation may own the port. Check again after stopping it.
    Write-OK "Existing service found; its port will be checked after it stops"
} else {
    $portInUse = @(Get-NetTCPConnection -LocalPort $McpPort -State Listen -ErrorAction SilentlyContinue)
    if ($portInUse.Count -gt 0) {
        Write-Fail "Port $McpPort is already listening. Set MCP_PORT to a free port in .env and re-run."
    }
    Write-OK "Port $McpPort is free"
}

# ── Step 8: Locate or install servy-cli (Windows service manager) ────────────
#
# servy-cli is a modern NSSM alternative. We use the net48 installer — it
# requires only .NET Framework 4.8, which ships with every Windows 10/11
# installation. The installer is a standard Inno Setup exe that accepts /SILENT.

Write-Step "Locating servy-cli (Windows service manager)..."

# Helper: find servy-cli.exe on PATH or in common install locations
function Find-ServyCli {
    $cmd = Get-Command servy-cli -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        "$env:ProgramFiles\Servy\servy-cli.exe",
        "$env:ProgramFiles\servy\servy-cli.exe",
        "${env:ProgramFiles(x86)}\Servy\servy-cli.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    return $null
}

$ServyExe = Find-ServyCli

if ($ServyExe) {
    Write-OK "servy-cli found at $ServyExe"
} else {
    # Download and run the net48 installer silently
    $ServyVersion     = "7.8"
    $ServyInstaller   = "servy-$ServyVersion-net48-x64-installer.exe"
    $ServyInstallerUrl = "https://github.com/aelassas/servy/releases/download/v$ServyVersion/$ServyInstaller"
    # SHA-256 from https://github.com/aelassas/servy/releases/tag/v7.8
    $ServyInstallerSha256 = "2bbd860644d78760748dc2dd63e68e5c09d9c7c190753296b0b3fd75f87e836f"
    $ServyInstallerPath = Join-Path $env:TEMP $ServyInstaller

    try {
        Write-Host "    Downloading installer from $ServyInstallerUrl ..." -ForegroundColor Yellow
        Invoke-WebRequest -Uri $ServyInstallerUrl -OutFile $ServyInstallerPath -UseBasicParsing -TimeoutSec 60
        Write-OK "Download complete"
    } catch {
        Write-Host ""
        Write-Host "  servy-cli download failed: $_" -ForegroundColor Red
        Write-Host ""
        Write-Host "  Install manually — choose one option:" -ForegroundColor Yellow
        Write-Host "    A) winget:  winget install servy"
        Write-Host "    B) Browser: https://github.com/aelassas/servy/releases/latest"
        Write-Host "               Download $ServyInstaller and run it"
        Write-Host "  Then re-run this script."
        Write-Host ""
        exit 1
    }

    $actualHash = (Get-FileHash -Path $ServyInstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $ServyInstallerSha256) {
        Remove-Item $ServyInstallerPath -Force -ErrorAction SilentlyContinue
        Write-Fail "servy installer SHA-256 mismatch; refusing to run it."
    }
    Write-OK "Installer SHA-256 verified"

    Write-Host "    Running installer silently..." -ForegroundColor Yellow
    $proc = Start-Process -FilePath $ServyInstallerPath -ArgumentList "/SILENT" -Wait -PassThru
    Remove-Item $ServyInstallerPath -Force -ErrorAction SilentlyContinue

    if ($proc.ExitCode -ne 0) {
        Write-Fail "servy installer exited with code $($proc.ExitCode). Try running it manually."
    }

    # Refresh PATH so newly installed servy-cli is visible in this session
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH", "User")

    $ServyExe = Find-ServyCli
    if (-not $ServyExe) {
        Write-Fail "servy-cli.exe not found after installation. Try opening a new Administrator PowerShell and re-running."
    }
    Write-OK "servy-cli installed at $ServyExe"
}

# ── Step 9: Install Windows service ───────────────────────────────────────────

Write-Step "Installing mcpvectordb-chatgpt Windows service..."

$ProjectDir  = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$UvPath      = (Get-Command uv).Source

# Remove existing service if present (idempotent re-run)
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Warn "Service '$ServiceName' already exists — removing and reinstalling..."
    try { & $ServyExe stop --name=$ServiceName 2>&1 | Out-Null } catch {}
    # Wait for the previous process to release its listener before reinstalling.
    for ($attempt = 0; $attempt -lt 15; $attempt++) {
        $portInUse = @(Get-NetTCPConnection -LocalPort $McpPort -State Listen -ErrorAction SilentlyContinue)
        if ($portInUse.Count -eq 0) { break }
        Start-Sleep -Seconds 1
    }
    if ($portInUse.Count -gt 0) {
        try { & $ServyExe start --name=$ServiceName 2>&1 | Out-Null } catch {}
        Write-Fail "Port $McpPort is still listening after stopping '$ServiceName'. Choose a free MCP_PORT."
    }
    & $ServyExe uninstall --name=$ServiceName
    if ($LASTEXITCODE -ne 0) { Write-Fail "Failed to remove existing service '$ServiceName'. Stop it manually and re-run." }
    Write-OK "Existing service removed"
}

# Build --env value: semicolons as delimiters; backslashes in paths must be escaped.
# servy-cli format: "VAR1=value1;VAR2=value2"
# Backslashes in values must be doubled (\\) per servy-cli escaping rules.
$LanceDirEsc  = $LanceDir  -replace '\\', '\\'
$ModelsDirEsc = $ModelsDir -replace '\\', '\\'
$EnvVars = "MCP_TRANSPORT=streamable-http;MCP_HOST=127.0.0.1;MCP_PORT=$McpPort;LANCEDB_URI=$LanceDirEsc;FASTEMBED_CACHE_PATH=$ModelsDirEsc;HF_HOME=$ModelsDirEsc;LOG_LEVEL=INFO"

# Loopback only: the service runs as SYSTEM with no auth, so it must not be reachable
# from the network. tailscale serve reaches it on 127.0.0.1 and forwards the tailnet
# hostname as Host, which FastMCP rejects on a loopback bind unless it is allowed.
$AllowedHosts = $env:ALLOWED_HOSTS
if (-not $AllowedHosts -and (Get-Command tailscale -ErrorAction SilentlyContinue)) {
    try {
        $AllowedHosts = ((tailscale status --json | Out-String | ConvertFrom-Json).Self.DNSName).TrimEnd(".")
    } catch {
        $AllowedHosts = $null
    }
}
if ($AllowedHosts) {
    $EnvVars += ";ALLOWED_HOSTS=$AllowedHosts"
    Write-OK "Allowing Host header: $AllowedHosts"
} else {
    Write-Warn "Tailscale hostname not found; ChatGPT requests will get HTTP 421 (Invalid Host header)."
    Write-Warn "Install and log in to Tailscale, or set `$env:ALLOWED_HOSTS='<your-tailscale-hostname>', then re-run."
}

# Build argument list as an array so PowerShell does not tokenise on semicolons inside $EnvVars.
# Each array element becomes exactly one argument passed to the process.
# Flag and value are kept as a single "flag=value" element; servy-cli accepts both --flag=val and --flag val.
$UvParams = "run --directory `"$ProjectDir`" mcpvectordb"
$installArgs = @(
    "install",
    "--name", $ServiceName,
    "--displayName", "mcpvectordb ChatGPT",
    "--description", "mcpvectordb MCP server (streamable-http) for ChatGPT Desktop",
    "--path", $UvPath,
    "--params", $UvParams,
    "--startupDir", $ProjectDir,
    "--startupType", "Automatic",
    "--stdout", $LogFile,
    "--stderr", $LogFile,
    "--enableSizeRotation",
    "--rotationSize", "10",
    "--maxRotations", "5",
    "--env", $EnvVars
)

& $ServyExe @installArgs

if ($LASTEXITCODE -ne 0) { Write-Fail "servy-cli install failed" }

Write-OK "Service '$ServiceName' installed"
Write-Warn "The service runs as SYSTEM. On domain-joined machines verify SYSTEM has read/write access to $DataDir"

# ── Step 10: Start service ─────────────────────────────────────────────────────

Write-Step "Starting service..."
& $ServyExe start --name=$ServiceName
if ($LASTEXITCODE -ne 0) { Write-Fail "Service failed to start. Check logs at: $LogFile" }

# The process loads the embedding model and tokenizer before binding the port.
# Wait for that bind so setup does not claim success for a service that crashed.
$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    $listener = @(Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $McpPort -State Listen -ErrorAction SilentlyContinue)
    if ($listener.Count -gt 0) { $ready = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $ready) { Write-Fail "Service did not listen on 127.0.0.1:$McpPort within 30 seconds. Check logs at: $LogFile" }
Write-OK "Service is listening on 127.0.0.1:$McpPort"

# ── Step 11: Print URL and instructions ───────────────────────────────────────

Write-Host ""
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  mcpvectordb is now running as a Windows service." -ForegroundColor White
Write-Host "  It will start automatically when Windows boots." -ForegroundColor White
Write-Host ""
Write-Host "  The server is running on http://127.0.0.1:${McpPort}/mcp (this PC only)" -ForegroundColor White
Write-Host ""
Write-Host "  ChatGPT Desktop requires HTTPS. Use Tailscale serve to expose the server:" -ForegroundColor Yellow
Write-Host ""
Write-Host "      tailscale serve --bg http://127.0.0.1:${McpPort}" -ForegroundColor White
Write-Host ""
Write-Host "  Then paste the resulting URL (with /mcp appended) into ChatGPT Desktop:" -ForegroundColor Yellow
Write-Host "  Settings → Apps → Advanced settings → Developer mode" -ForegroundColor Yellow
Write-Host ""
Write-Host "      https://<your-tailscale-hostname>/mcp" -ForegroundColor White
Write-Host ""
Write-Host "  Then open a new ChatGPT conversation and ask:" -ForegroundColor Cyan
Write-Host "      'List all libraries'" -ForegroundColor White
Write-Host "  to confirm the server is connected." -ForegroundColor Cyan
Write-Host ""
Write-Host "  Service log: $LogFile" -ForegroundColor DarkGray
Write-Host "  To uninstall: .\scripts\uninstall-chatgpt-windows.ps1" -ForegroundColor DarkGray
Write-Host ""
