# Windows 11 Installation — mcpvectordb for ChatGPT Desktop

Native Windows 11 setup: no Docker, no WSL. Connects `mcpvectordb` to the
ChatGPT Desktop app via a persistent background Windows service.

> **Why a service?** ChatGPT Desktop on Windows is distributed as a Store (AppX) app
> and cannot launch child processes directly. It connects to MCP servers via URL.
> The Windows service keeps `mcpvectordb` running in the background so ChatGPT Desktop
> can reach it at any time.

---

## Requirements

- Windows 11 (x64)
- [uv](https://docs.astral.sh/uv/) — Python package manager
- Python **3.11–3.13** — installed automatically via uv
- [ChatGPT Desktop for Windows](https://openai.com/chatgpt/download/) (Plus/Pro/Team account)
- Visual C++ Redistributable 2019 or later — required by ONNX Runtime
  - Download: [aka.ms/vs/17/release/vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe)
- Administrator access (required to install a Windows service)
- [Tailscale](https://tailscale.com/download/windows) — ChatGPT Desktop only connects over
  HTTPS, and `tailscale serve` provides it

---

## Install

1. Keep the checkout in a directory writable only by Administrators and SYSTEM,
   such as `C:\Program Files\mcpvectordb`. Open PowerShell **as Administrator**
   and navigate to it:

   ```powershell
   cd "C:\Program Files\mcpvectordb"
   ```

2. Run the setup script:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\setup-chatgpt-windows.ps1
   ```

   Windows blocks downloaded scripts by default; `-ExecutionPolicy Bypass` allows this
   one run without changing your system setting.

   The script:
   - Checks uv and Python 3.13
   - Runs `uv sync` to install all Python dependencies
   - Pre-downloads the embedding model and tokenizer (~600 MB) to `C:\ProgramData\mcpvectordb\models`
   - Creates the LanceDB data directory and generates `.env`
   - Installs [servy](https://github.com/aelassas/servy) (a Windows service manager) if
     `servy-cli` is not already installed
   - Installs and starts the `mcpvectordb-chatgpt` service (`streamable-http` on
     `127.0.0.1:8000`, starting automatically), allowing your Tailscale hostname in the
     `Host` header
   - Prints the next steps

3. Restrict access to this PC's HTTPS port (443) to the intended users or devices
   with [Tailscale grants](https://tailscale.com/docs/features/access-control/grants).
   Check existing broad grants too: permissions are additive. Then expose the server
   over HTTPS on your tailnet:

   ```powershell
   tailscale serve --bg http://127.0.0.1:8000
   ```

   Use your `MCP_PORT` instead of 8000 if you changed it.

4. Open ChatGPT Desktop and go to:

   **Settings → Apps → Advanced settings → Developer mode**

   Add the URL `https://<your-tailscale-hostname>/mcp` and save.

5. Open a new ChatGPT conversation and ask:

   > "List all libraries"

   ChatGPT should respond with an empty libraries list (no error). That confirms
   the server is connected.

> **Security:** the service has no sign-in and runs as `SYSTEM`, so it listens on
> `127.0.0.1` only; other devices cannot reach port 8000 directly. Anyone on your tailnet
> who can open the `tailscale serve` URL can read, add and delete documents, and can ask
> the server to ingest any file the SYSTEM account can read on this PC. Grant
> access to this Serve endpoint only to people and devices you trust. Do not use
> Tailscale Funnel, which would publish the endpoint on the public internet.
> Because SYSTEM executes code from the checkout, keep that directory protected
> from writes by unelevated users or programs too. The service also launches `uv`
> and a Python interpreter; protect those installed paths. A dedicated,
> low-privilege service account is recommended before use on a shared PC.

---

## Add Your Documents

The library starts empty. Give the **full path** of a file or folder on this PC:

> "Add `C:\Users\you\Documents\Reports` to a library called reports."
>
> "Add https://example.com/guide to a library called research."

To bulk-load a large folder, run from the project directory in an **Administrator**
PowerShell. Set the paths explicitly so the loader uses the service's database and
model cache even if an older `.env` points to your user profile:

```powershell
$env:LANCEDB_URI = Join-Path $env:ProgramData "mcpvectordb\lancedb"
$env:FASTEMBED_CACHE_PATH = Join-Path $env:ProgramData "mcpvectordb\models"
$env:HF_HOME = $env:FASTEMBED_CACHE_PATH
uv run mcpvectordb-ingest "C:\Users\you\Documents\Reports" --library reports
```

Supported formats are PDF (with a text layer), `.docx`, `.pptx`, `.xlsx`/`.xls`,
HTML, `.txt`, `.md`, `.csv`, `.json`, `.xml` and `.zip`; images, audio, `.doc` and
`.ppt` are refused. See [Supported file types](../README.md#supported-file-types).

---

## Embedding Model — Pre-Downloaded

The setup script downloads `nomic-embed-text-v1.5` and its tokenizer (~600 MB) into
`C:\ProgramData\mcpvectordb\models` during setup. The service starts instantly
on every subsequent boot — no first-run download delay.

To re-download manually, run from the project directory in an Administrator PowerShell
and point both caches at the service's location:

```powershell
$env:FASTEMBED_CACHE_PATH = Join-Path $env:ProgramData "mcpvectordb\models"
$env:HF_HOME = $env:FASTEMBED_CACHE_PATH
uv run mcpvectordb-download-model
```

---

## Data Directory Layout

```
C:\Program Files\mcpvectordb\          ← App code (administrator-protected checkout)
├── src\
├── scripts\
│   ├── setup-chatgpt-windows.ps1
│   └── uninstall-chatgpt-windows.ps1
└── .env                                 ← Generated by setup script

C:\ProgramData\mcpvectordb\               ← Runtime data (readable by the SYSTEM service)
├── lancedb\                             ← Vector database (LANCEDB_URI)
├── models\                              ← Embedding model cache
└── chatgpt-service.log                  ← Service log (stdout + stderr)
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

# Restart after changing other .env settings
sc.exe stop mcpvectordb-chatgpt; sc.exe start mcpvectordb-chatgpt
```

The service sets transport, loopback host, database path and model cache itself;
those settings override `.env`. Setup reads `MCP_PORT` from `.env` and reinstalls
the service when you re-run it. An existing `.env` for a different client is kept.
To change the service's fixed data paths, edit the setup script before re-running.
Keep the host bound to `127.0.0.1`.

Logs are at `%ProgramData%\mcpvectordb\chatgpt-service.log`.

---

## Uninstall

Run as Administrator:

```powershell
.\scripts\uninstall-chatgpt-windows.ps1
```

The script stops and removes the service. You will be prompted whether to delete
`C:\ProgramData\mcpvectordb` (LanceDB index, cached model and service log). The
source code directory is never deleted.

---

## Common Issues

| Symptom                                           | Fix                                                                                                                                 |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| "Must be run as Administrator"                    | Right-click PowerShell → Run as Administrator                                                                                       |
| `uv: command not found`                           | Run `irm https://astral.sh/uv/install.ps1 \| iex`, open a new terminal                                                              |
| `onnxruntime` has no wheel for `cp314`            | Python 3.14 not yet supported — run `uv python install 3.13` then re-run setup                                                      |
| `DLL load failed` or `VCRUNTIME140.dll not found` | Install [Visual C++ Redistributable 2019+](https://aka.ms/vs/17/release/vc_redist.x64.exe)                                          |
| "Port 8000 is already in use"                     | Set `MCP_PORT=<free port>` in `.env` and re-run setup                                                                               |
| servy download fails                              | Run `winget install servy`, or install it from [github.com/aelassas/servy/releases](https://github.com/aelassas/servy/releases/latest), then re-run |
| ChatGPT gets HTTP 421 `Invalid Host header`       | Install and log in to Tailscale, then re-run setup; or run it with `$env:ALLOWED_HOSTS='<your-tailscale-hostname>'` |
| ChatGPT Desktop shows no tools                    | Verify the URL matches what the script printed; check service is running with `Get-Service mcpvectordb-chatgpt`                     |
| Service starts but ChatGPT can't connect          | Confirm Developer mode is enabled in ChatGPT Desktop settings; try restarting ChatGPT Desktop                                       |
| Service won't start                               | Check `%ProgramData%\mcpvectordb\chatgpt-service.log` for the error                                                                |
| Existing `.env` uses another transport or data path | The service overrides these settings. Set the ProgramData paths explicitly for manual loader commands as shown above. |
| "running scripts is disabled on this system"      | Run the script with `powershell -ExecutionPolicy Bypass -File .\scripts\setup-chatgpt-windows.ps1` |
| `Cannot ingest 'x.jpg'` (or `.doc`, `.mp3`)        | Format not supported; the message says what to do (run OCR, save as `.docx`/`.pptx`, transcribe locally) |
