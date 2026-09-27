#Requires -Version 5.1
<#
.SYNOPSIS
    Remove the mcpvectordb-chatgpt Windows service installed by setup-chatgpt-windows.ps1.

.NOTES
    Must be run as Administrator.
    Data directories (LanceDB, models) are preserved by default — you will be prompted.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Helpers ────────────────────────────────────────────────────────────────────

function Write-Step { param([string]$Message) Write-Host "`n>>> $Message" -ForegroundColor Cyan }
function Write-OK   { param([string]$Message) Write-Host "    OK  $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "    WARN $Message" -ForegroundColor Yellow }
function Write-Fail { param([string]$Message) Write-Host "    FAIL $Message" -ForegroundColor Red; exit 1 }

# ── Require Administrator ──────────────────────────────────────────────────────

Write-Step "Checking for Administrator privileges..."
$currentPrincipal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "  This script must be run as Administrator." -ForegroundColor Red
    exit 1
}
Write-OK "Running as Administrator"

# ── Locate servy-cli ──────────────────────────────────────────────────────────

$ServyExe = Join-Path $PSScriptRoot "servy\servy-cli.exe"
if (-not (Test-Path $ServyExe)) {
    # Fall back to system PATH (winget/choco install puts it there)
    $servyCmd = Get-Command servy-cli -ErrorAction SilentlyContinue
    $ServyExe = if ($servyCmd) { $servyCmd.Source } else { $null }
    if (-not $ServyExe) { Write-Fail "servy-cli.exe not found. Run setup-chatgpt-windows.ps1 first." }
}

# ── Stop and remove service ────────────────────────────────────────────────────

$ServiceName = "mcpvectordb-chatgpt"

Write-Step "Stopping service '$ServiceName'..."
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Warn "Service '$ServiceName' not found — nothing to remove."
} else {
    try { & $ServyExe stop --name=$ServiceName 2>&1 | Out-Null } catch {}
    Start-Sleep -Seconds 2
    & $ServyExe uninstall --name=$ServiceName
    if ($LASTEXITCODE -ne 0) { Write-Fail "Failed to remove service '$ServiceName'." }
    Write-OK "Service '$ServiceName' removed"
}

# ── Optionally delete data directories ────────────────────────────────────────

$DataDir = Join-Path $env:LOCALAPPDATA "mcpvectordb"

Write-Host ""
$deleteData = Read-Host "Delete data directories ($DataDir)? This removes your LanceDB index and cached model. [y/N]"
if ($deleteData -eq "y" -or $deleteData -eq "Y") {
    if (Test-Path $DataDir) {
        Remove-Item $DataDir -Recurse -Force
        Write-OK "Deleted $DataDir"
    } else {
        Write-Warn "$DataDir does not exist — nothing to delete"
    }
} else {
    Write-OK "Data directories preserved at $DataDir"
}

Write-Host ""
Write-Host "  Uninstall complete." -ForegroundColor Green
Write-Host "  Remember to remove the URL from ChatGPT Desktop Developer mode settings." -ForegroundColor Yellow
Write-Host ""
