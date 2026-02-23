# Windows 11 Installation — mcpvectordb

Native Windows 11 setup: no Docker, no WSL, direct Claude Desktop integration via `stdio`.
Two deployment options: **Python + uv** (developer-friendly) or **standalone `.exe`** (no Python needed).

## Requirements

### Python + uv option
- Windows 11 (x64)
- [uv](https://docs.astral.sh/uv/) — Python package manager
- Python 3.11 or later (installable via `uv python install 3.11`)
- [Claude Desktop for Windows](https://claude.ai/download)
- Visual C++ Redistributable 2019 or later — required by ONNX Runtime
  - Download: [aka.ms/vs/17/release/vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe)

### Standalone `.exe` option
- Windows 11 (x64) — **no Python installation required on target machine**
- Visual C++ Redistributable 2019 or later (same link above)
- [Claude Desktop for Windows](https://claude.ai/download)
- Build machine additionally needs: uv, Python 3.11+

---

## Option A — Python + uv (recommended for developers)

### Install

1. Open PowerShell and navigate to the project directory:
   ```powershell
   cd C:\path\to\mcpvectordb
   ```

2. Run the bootstrapper:
   ```powershell
   .\scripts\setup-windows.ps1
   ```
   The script:
   - Checks uv and Python 3.11+
   - Runs `uv sync` to install all Python dependencies
   - **Pre-downloads the embedding model** (~500 MB ONNX) to `AppData\Local\mcpvectordb\models`
   - Creates LanceDB data directory
   - Generates `.env` with Windows-appropriate paths
   - Prints the Claude Desktop config block

3. Copy the printed JSON block and paste it into:
   ```
   %APPDATA%\Claude\claude_desktop_config.json
   ```

4. Restart Claude Desktop.

### Embedding model — pre-downloaded, not on first run

The setup script runs `uv run mcpvectordb-download-model` which downloads
`nomic-embed-text-v1.5` (~500 MB) into `AppData\Local\mcpvectordb\models`.
The server starts instantly on every subsequent launch — no first-run download.

To re-download manually:
```powershell
uv run mcpvectordb-download-model
```

---

## Option B — Standalone `.exe` (no Python on target machine)

Build a single executable file that contains the MCP server, all dependencies,
and the embedding model. Copy it to any Windows 11 machine and run it — no
installation required.

### Build

1. Install build prerequisites on the **build machine** (one-time):
   ```powershell
   # uv, Python 3.11 — same as Option A
   .\scripts\setup-windows.ps1
   ```

2. Build the `.exe`:
   ```powershell
   .\scripts\build-windows.ps1
   ```
   The script downloads the embedding model (if not already in `build_models\`),
   then runs PyInstaller. Output: `dist\mcpvectordb.exe` (~800 MB–1 GB).

3. Copy `dist\mcpvectordb.exe` to the target machine.

4. Add to `%APPDATA%\Claude\claude_desktop_config.json` on the target machine:
   ```json
   {
     "mcpServers": {
       "mcpvectordb": {
         "command": "C:\\path\\to\\mcpvectordb.exe",
         "args": [],
         "env": {
           "MCP_TRANSPORT": "stdio",
           "LANCEDB_URI": "C:\\Users\\<you>\\AppData\\Local\\mcpvectordb\\lancedb",
           "LOG_LEVEL": "INFO"
         }
       }
     }
   }
   ```

5. Restart Claude Desktop on the target machine.

**What's bundled in the `.exe`:**
- Complete mcpvectordb MCP server
- LanceDB vector store with full-text search (tantivy)
- nomic-embed-text-v1.5 ONNX embedding model — **no download on first run**
- MarkItDown converters (PDF, Word, PowerPoint, Excel, HTML, and more)
- All Python runtime dependencies

---

## Verify (both options)

After restarting Claude Desktop, open a new conversation and check that the
`mcpvectordb` tools appear in the tools list (hammer icon). Then run:

> "List all libraries"

Claude should respond with an empty libraries list (no error). That confirms the
server started and connected successfully.

---

## Data Directory Layout

Three directories remain fully separate:

```
C:\Users\<you>\
├── mcpvectordb\                          ← App code (git clone here)
│   ├── src\
│   ├── pyproject.toml
│   └── .env                             ← optional local overrides
│
└── AppData\Local\mcpvectordb\           ← Runtime data (separate from code)
    ├── lancedb\                         ← Vector database (LANCEDB_URI)
    ├── models\                          ← Embedding model cache (pre-downloaded)
    └── server.log                       ← Optional log file (set LOG_FILE to enable)

C:\Users\<you>\Documents\               ← Your input documents (any path)
    (pass any path to the ingest_file tool — no constraints)
```

For the `.exe` option, the embedding model is bundled **inside** the exe.
The LanceDB data directory is still external (configured via `LANCEDB_URI`).

All paths are overridable via `.env` or the `env` block in `claude_desktop_config.json`.

---

## Common Issues

| Symptom | Fix |
|---------|-----|
| `DLL load failed` or `VCRUNTIME140.dll not found` | Install [Visual C++ Redistributable 2019+](https://aka.ms/vs/17/release/vc_redist.x64.exe) and restart |
| `uv: command not found` in PowerShell | Run `irm https://astral.sh/uv/install.ps1 \| iex`, then open a new terminal |
| Claude Desktop shows no tools | Verify the JSON in `claude_desktop_config.json` is valid; check paths are correct |
| Server hangs on first start (Python option) | Model may not have been pre-downloaded — run `uv run mcpvectordb-download-model` |
| `ingest_file` error: path not found | Use a full absolute path (e.g. `C:\Users\you\Documents\report.pdf`); `~\` is also supported |
| `.exe` antivirus warning | Add `mcpvectordb.exe` to your antivirus exclusions; false-positive common with PyInstaller bundles |
| `.exe` first launch slow (5–10 s) | Normal — PyInstaller extracts the bundle to a temp directory on first launch |
