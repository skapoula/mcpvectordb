# ChatGPT Desktop Windows Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a `WindowsOS-ChatGPT` branch that lets Windows 11 users connect `mcpvectordb` to ChatGPT Desktop via a one-script setup that installs it as a persistent Windows background service.

**Architecture:** ChatGPT Desktop (AppX/Store) cannot spawn child processes, so it only accepts a URL. The server runs with `MCP_TRANSPORT=sse` bound to `127.0.0.1:8000`, managed by NSSM as a Windows service that auto-starts at login. No changes to `src/mcpvectordb/` — all work is in scripts and docs.

**Tech Stack:** PowerShell 5.1+, NSSM 2.24 (auto-downloaded), uv, Python 3.13, existing `mcpvectordb` SSE transport.

---

## File Map

| File                                    | Action     | Responsibility                                                        |
| --------------------------------------- | ---------- | --------------------------------------------------------------------- |
| `scripts/setup-chatgpt-windows.ps1`     | **Create** | Full setup: prereqs → deps → model → NSSM service install → print URL |
| `scripts/uninstall-chatgpt-windows.ps1` | **Create** | Stop + remove NSSM service; optionally delete data dirs               |
| `docs/chatgpt-windows-setup.md`         | **Create** | User-facing install guide for ChatGPT Desktop on Windows 11           |

No files in `src/` are modified.

---

## Task 1: Create the `WindowsOS-ChatGPT` branch

**Files:** none (git only)

- [ ] **Step 1: Create branch from `windowsOS`**

  ```powershell
  git checkout windowsOS
  git checkout -b WindowsOS-ChatGPT
  ```

  Expected: `Switched to a new branch 'WindowsOS-ChatGPT'`

- [ ] **Step 2: Verify branch**

  ```powershell
  git branch
  ```

  Expected: `* WindowsOS-ChatGPT` is current, `windowsOS` is listed.

---

## Task 2: Create `scripts/setup-chatgpt-windows.ps1`

**Files:**

- Create: `scripts/setup-chatgpt-windows.ps1`

This script is the entire user-facing setup experience. It mirrors `setup-windows.ps1`
for steps 1–6 (prereqs, deps, model, dirs, .env), then diverges: instead of printing a
JSON config block, it downloads NSSM and installs a Windows service.

> **Note on .env handling:** The script checks if `.env` already exists and skips
> generation if so (same as `setup-windows.ps1`). This allows users who already ran
> `setup-windows.ps1` to re-use their existing `.env` — but the service needs
> `MCP_TRANSPORT=sse`, so the script warns if the existing `.env` has `MCP_TRANSPORT=stdio`.

- [ ] **Step 1: Create the file with the full script content**

  Create `scripts/setup-chatgpt-windows.ps1` with exactly this content:

  ```powershell
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

  Write-Step "Checking port 8000..."
  $portInUse = netstat -ano | Select-String ":8000 "
  if ($portInUse) {
      Write-Warn "Port 8000 is already in use. Set MCP_PORT to a free port in .env and re-run."
      Write-Warn "Processes using port 8000:"
      $portInUse | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
      exit 1
  }
  Write-OK "Port 8000 is free"

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
      $entry = $zip.Entries | Where-Object { $_.FullName -eq "nssm-2.24/win64/nssm.exe" }
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
      & $NssmExe stop $ServiceName 2>$null
      Start-Sleep -Seconds 2
      & $NssmExe remove $ServiceName confirm
      Write-OK "Existing service removed"
  }

  # Install service
  & $NssmExe install $ServiceName $UvPath "run" "--directory" $ProjectDir "mcpvectordb"
  if ($LASTEXITCODE -ne 0) { Write-Fail "nssm install failed" }

  # Configure environment variables (passed directly to the service process)
  & $NssmExe set $ServiceName AppEnvironmentExtra `
      "MCP_TRANSPORT=sse" `
      "MCP_HOST=127.0.0.1" `
      "MCP_PORT=8000" `
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
  Write-Host "      http://127.0.0.1:8000/sse" -ForegroundColor White
  Write-Host ""
  Write-Host "  Then open a new ChatGPT conversation and ask:" -ForegroundColor Cyan
  Write-Host "      'List all libraries'" -ForegroundColor White
  Write-Host "  to confirm the server is connected." -ForegroundColor Cyan
  Write-Host ""
  Write-Host "  Service log: $LogFile" -ForegroundColor DarkGray
  Write-Host "  To uninstall: .\scripts\uninstall-chatgpt-windows.ps1" -ForegroundColor DarkGray
  Write-Host ""
  ```

- [ ] **Step 2: Verify the file was created**

  ```powershell
  Test-Path scripts\setup-chatgpt-windows.ps1
  ```

  Expected: `True`

- [ ] **Step 3: Commit**

  ```bash
  git add scripts/setup-chatgpt-windows.ps1
  git commit -m "feat(chatgpt-windows): add setup script for ChatGPT Desktop SSE service"
  ```

---

## Task 3: Create `scripts/uninstall-chatgpt-windows.ps1`

**Files:**

- Create: `scripts/uninstall-chatgpt-windows.ps1`

- [ ] **Step 1: Create the file**

  Create `scripts/uninstall-chatgpt-windows.ps1` with exactly this content:

  ```powershell
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

  # ── Locate NSSM ───────────────────────────────────────────────────────────────

  $NssmExe = Join-Path $PSScriptRoot "nssm\nssm.exe"
  if (-not (Test-Path $NssmExe)) {
      # Fall back to system PATH
      $NssmExe = (Get-Command nssm -ErrorAction SilentlyContinue)?.Source
      if (-not $NssmExe) { Write-Fail "nssm.exe not found. Run setup-chatgpt-windows.ps1 first." }
  }

  # ── Stop and remove service ────────────────────────────────────────────────────

  $ServiceName = "mcpvectordb-chatgpt"

  Write-Step "Stopping service '$ServiceName'..."
  $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
  if (-not $svc) {
      Write-Warn "Service '$ServiceName' not found — nothing to remove."
  } else {
      & $NssmExe stop $ServiceName 2>$null
      Start-Sleep -Seconds 2
      & $NssmExe remove $ServiceName confirm
      if ($LASTEXITCODE -ne 0) { Write-Fail "Failed to remove service" }
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
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add scripts/uninstall-chatgpt-windows.ps1
  git commit -m "feat(chatgpt-windows): add uninstall script for ChatGPT Desktop service"
  ```

---

## Task 4: Create `docs/chatgpt-windows-setup.md`

**Files:**

- Create: `docs/chatgpt-windows-setup.md`

- [ ] **Step 1: Create the file**

  Create `docs/chatgpt-windows-setup.md` with exactly this content:

  ````markdown
  # Windows 11 Installation — mcpvectordb for ChatGPT Desktop

  Native Windows 11 setup: no Docker, no WSL. Connects `mcpvectordb` to the
  ChatGPT Desktop app via a persistent background Windows service.

  > **Why a service?** ChatGPT Desktop on Windows is distributed as a Store (AppX) app
  > and cannot launch child processes directly. It connects to MCP servers via URL.
  > The Windows service keeps `mcpvectordb` running in the background so ChatGPT Desktop
  > can reach it at `http://127.0.0.1:8000/sse` at any time.

  ---

  ## Requirements

  - Windows 11 (x64)
  - [uv](https://docs.astral.sh/uv/) — Python package manager
  - Python **3.11–3.13** — installed automatically via uv
  - [ChatGPT Desktop for Windows](https://openai.com/chatgpt/download/) (Plus/Pro/Team account)
  - Visual C++ Redistributable 2019 or later — required by ONNX Runtime
    - Download: [aka.ms/vs/17/release/vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe)
  - Administrator access (required to install a Windows service)

  ---

  ## Install

  1. Open PowerShell **as Administrator** and navigate to the project directory:

     ```powershell
     cd C:\path\to\mcpvectordb
     ```

  2. Run the setup script:

     ```powershell
     .\scripts\setup-chatgpt-windows.ps1
     ```

     The script:
     - Checks uv and Python 3.13
     - Runs `uv sync` to install all Python dependencies
     - Pre-downloads the embedding model (~500 MB ONNX) to `AppData\Local\mcpvectordb\models`
     - Creates the LanceDB data directory
     - Downloads NSSM (a small service manager) to `scripts\nssm\`
     - Installs and starts `mcpvectordb` as a Windows background service
     - Prints the URL to paste into ChatGPT Desktop

  3. Copy the printed URL:

     ```
     http://127.0.0.1:8000/sse
     ```

  4. Open ChatGPT Desktop and go to:

     **Settings → Apps → Advanced settings → Developer mode**

     Paste the URL and save.

  5. Open a new ChatGPT conversation and ask:

     > "List all libraries"

     ChatGPT should respond with an empty libraries list (no error). That confirms
     the server is connected.

  ---

  ## Embedding Model — Pre-Downloaded

  The setup script downloads `nomic-embed-text-v1.5` (~500 MB) into
  `AppData\Local\mcpvectordb\models` during setup. The service starts instantly
  on every subsequent boot — no first-run download delay.

  To re-download manually (run as Administrator):

  ```powershell
  uv run mcpvectordb-download-model
  ```

  ---

  ## Data Directory Layout

  ```
  C:\Users\<you>\
  ├── mcpvectordb\                          ← App code (git clone here)
  │   ├── src\
  │   ├── scripts\
  │   │   ├── setup-chatgpt-windows.ps1
  │   │   ├── uninstall-chatgpt-windows.ps1
  │   │   └── nssm\nssm.exe               ← Downloaded by setup script
  │   └── .env                             ← Generated by setup script
  │
  └── AppData\Local\mcpvectordb\           ← Runtime data (separate from code)
      ├── lancedb\                         ← Vector database (LANCEDB_URI)
      ├── models\                          ← Embedding model cache
      └── chatgpt-service.log             ← Service log (stdout + stderr)
  ```

  ---

  ## Managing the Service

  The service is named `mcpvectordb-chatgpt`. Standard Windows service commands work:

  ```powershell
  # Check status
  Get-Service mcpvectordb-chatgpt

  # Stop the service
  sc.exe stop mcpvectordb-chatgpt

  # Start the service
  sc.exe start mcpvectordb-chatgpt

  # Restart after changing .env
  sc.exe stop mcpvectordb-chatgpt; sc.exe start mcpvectordb-chatgpt
  ```

  Logs are at `%LOCALAPPDATA%\mcpvectordb\chatgpt-service.log`.

  ---

  ## Uninstall

  Run as Administrator:

  ```powershell
  .\scripts\uninstall-chatgpt-windows.ps1
  ```

  The script stops and removes the service. You will be prompted whether to delete
  the data directories (LanceDB index + cached model). The source code directory
  is never deleted.

  ---

  ## Common Issues

  | Symptom                                           | Fix                                                                                                                                 |
  | ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
  | "Must be run as Administrator"                    | Right-click PowerShell → Run as Administrator                                                                                       |
  | `uv: command not found`                           | Run `irm https://astral.sh/uv/install.ps1 \| iex`, open a new terminal                                                              |
  | `onnxruntime` has no wheel for `cp314`            | Python 3.14 not yet supported — run `uv python install 3.13` then re-run setup                                                      |
  | `DLL load failed` or `VCRUNTIME140.dll not found` | Install [Visual C++ Redistributable 2019+](https://aka.ms/vs/17/release/vc_redist.x64.exe)                                          |
  | "Port 8000 is already in use"                     | Set `MCP_PORT=<free port>` in `.env` and re-run setup                                                                               |
  | NSSM download fails                               | Download `nssm-2.24.zip` from [nssm.cc](https://nssm.cc/download), extract `win64\nssm.exe` to `scripts\nssm\nssm.exe`, then re-run |
  | ChatGPT Desktop shows no tools                    | Verify the URL is `http://127.0.0.1:8000/sse`; check service is running with `Get-Service mcpvectordb-chatgpt`                      |
  | Service starts but ChatGPT can't connect          | Confirm Developer mode is enabled in ChatGPT Desktop settings; try restarting ChatGPT Desktop                                       |
  | Service won't start                               | Check `%LOCALAPPDATA%\mcpvectordb\chatgpt-service.log` for the error                                                                |
  | `.env` has `MCP_TRANSPORT=stdio`                  | Edit `.env`, change to `MCP_TRANSPORT=sse`, restart the service                                                                     |
  ````

- [ ] **Step 2: Commit**

  ```bash
  git add docs/chatgpt-windows-setup.md
  git commit -m "docs(chatgpt-windows): add ChatGPT Desktop Windows setup guide"
  ```

---

## Task 5: Final verification and branch push-ready check

**Files:** none

- [ ] **Step 1: Confirm all new files exist**

  ```bash
  ls scripts/setup-chatgpt-windows.ps1 scripts/uninstall-chatgpt-windows.ps1 docs/chatgpt-windows-setup.md
  ```

  Expected: all three files listed, no errors.

- [ ] **Step 2: Confirm no `src/` files were modified**

  ```bash
  git diff windowsOS -- src/
  ```

  Expected: empty output (no diff).

- [ ] **Step 3: Confirm git log looks correct**

  ```bash
  git log --oneline windowsOS..HEAD
  ```

  Expected: exactly three commits (setup script, uninstall script, docs guide).

- [ ] **Step 4: Confirm branch is `WindowsOS-ChatGPT`**

  ```bash
  git branch --show-current
  ```

  Expected: `WindowsOS-ChatGPT`
