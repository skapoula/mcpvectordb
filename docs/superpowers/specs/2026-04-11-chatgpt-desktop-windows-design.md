# Design: mcpvectordb — ChatGPT Desktop Windows Integration

**Date:** 2026-04-11
**Branch:** `WindowsOS-ChatGPT` (branched from `windowsOS`)
**Status:** Approved

---

## Problem Statement

The `windowsOS` branch integrates `mcpvectordb` with Claude Desktop on Windows 11 via
`stdio` transport — Claude Desktop spawns the server as a child process. ChatGPT Desktop
on Windows 11 is distributed as an AppX/Store package, which sandboxes the app and
prevents it from spawning arbitrary child processes. It only accepts a **URL** pointing
to a running MCP server (SSE or streamable-http transport).

The goal is a separate branch (`WindowsOS-ChatGPT`) that gives ChatGPT Desktop users
the same semantic search capability, with the same one-script setup experience.

---

## Architecture

The MCP server core (`src/mcpvectordb/`) is **unchanged**. All new work is in the
Windows setup/deployment layer only.

```
mcpvectordb (SSE, http://127.0.0.1:8000/sse)
        ▲
        │  HTTP (loopback only — not exposed to network)
        │
ChatGPT Desktop (AppX)  ←── URL entered in:
                              Settings → Apps → Advanced settings → Developer mode

Windows Service (NSSM)
  └── manages: uv run mcpvectordb
               MCP_TRANSPORT=sse
               MCP_HOST=127.0.0.1
               MCP_PORT=8000
               (auto-starts at login, auto-restarts on crash)
```

### What changes vs `windowsOS`

| File                                    | Change                                      |
| --------------------------------------- | ------------------------------------------- |
| `scripts/setup-chatgpt-windows.ps1`     | **New** — installs NSSM service, prints URL |
| `scripts/uninstall-chatgpt-windows.ps1` | **New** — stops and removes service         |
| `docs/chatgpt-windows-setup.md`         | **New** — user-facing install guide         |
| `src/mcpvectordb/`                      | **No changes**                              |
| `scripts/setup-windows.ps1`             | **No changes**                              |
| `scripts/build-windows.ps1`             | **No changes**                              |

---

## Transport

- **Protocol:** SSE (`MCP_TRANSPORT=sse`)
- **Bind address:** `127.0.0.1` (loopback only — never `0.0.0.0`)
- **Port:** `8000` (default; user can override via `MCP_PORT` in `.env`)
- **URL for ChatGPT Desktop:** `http://127.0.0.1:8000/sse`
- **TLS/OAuth:** Not used for local-only setup (loopback binding provides sufficient isolation)

SSE chosen over `streamable-http` for broader MCP client compatibility and simplicity.

---

## Windows Service

- **Service name:** `mcpvectordb-chatgpt`
  (distinct name allows future coexistence with a Claude Desktop service)
- **Manager:** [NSSM](https://nssm.cc/) 2.24 — auto-downloaded by setup script
- **Process:** `uv run --directory <project_dir> mcpvectordb`
- **Startup type:** Automatic (starts at user login)
- **Recovery:** NSSM restarts the service on crash
- **Logs:** NSSM redirects stdout/stderr to
  `%LOCALAPPDATA%\mcpvectordb\chatgpt-service.log`
- **Environment variables:** Set on the service via `nssm set` (not inherited from shell)

---

## Setup Script: `setup-chatgpt-windows.ps1`

Steps (mirrors `setup-windows.ps1` structure; only steps 7–10 differ):

1. **Require Administrator** — detect elevation; exit with clear message if not elevated
2. **Check uv** — same check as `setup-windows.ps1`
3. **Ensure Python 3.13** — same auto-install via `uv python install 3.13`
4. **`uv sync`** — install all Python dependencies
5. **Pre-download embedding model** — `uv run mcpvectordb-download-model` (~500 MB, one-time)
6. **Create data directories** — LanceDB dir + models dir under `%LOCALAPPDATA%\mcpvectordb\`
7. **Generate `.env`** — with `MCP_TRANSPORT=sse`, `MCP_HOST=127.0.0.1`, `MCP_PORT=8000`
8. **Download NSSM** — fetch `nssm-2.24.zip` from `https://nssm.cc/release/nssm-2.24.zip`,
   extract `nssm.exe` (x64) to `scripts\nssm\nssm.exe`
9. **Install service** — `nssm install mcpvectordb-chatgpt <uv> run --directory <project> mcpvectordb`;
   set env vars, log paths, startup type via `nssm set`
10. **Start service** — `nssm start mcpvectordb-chatgpt`
11. **Print URL** — display `http://127.0.0.1:8000/sse` with instructions for ChatGPT Desktop

**Idempotency:** If run a second time, the script stops and removes the existing service
before reinstalling — safe to re-run after config changes.

---

## Uninstall Script: `uninstall-chatgpt-windows.ps1`

1. Stop service: `nssm stop mcpvectordb-chatgpt`
2. Remove service: `nssm remove mcpvectordb-chatgpt confirm`
3. Optionally delete data dirs (prompt user — default: keep data)
4. Confirm removal

---

## Error Handling

| Scenario                     | Handling                                                                   |
| ---------------------------- | -------------------------------------------------------------------------- |
| Not running as Administrator | Detect elevation, exit immediately with "Run as Administrator" message     |
| NSSM download fails          | Print error + manual download URL (`https://nssm.cc`), exit                |
| Port 8000 already in use     | Detect with `netstat -ano`, warn user, advise setting `MCP_PORT` in `.env` |
| Service already exists       | Stop + remove existing service, then reinstall                             |
| `uv` not on PATH             | Same error + install instructions as `setup-windows.ps1`                   |
| Python 3.13 unavailable      | Auto-install via `uv python install 3.13`                                  |
| Service fails to start       | Print log file path, suggest checking `chatgpt-service.log`                |

---

## User-Facing Instructions (summary for `docs/chatgpt-windows-setup.md`)

1. Open PowerShell **as Administrator** and run `.\scripts\setup-chatgpt-windows.ps1`
2. When complete, copy the printed URL: `http://127.0.0.1:8000/sse`
3. Open ChatGPT Desktop → Settings → Apps → Advanced settings → Developer mode → add the URL
4. In a new ChatGPT conversation, ask "List all libraries" to verify

To uninstall: `.\scripts\uninstall-chatgpt-windows.ps1`

---

## Testing

No new automated tests (server core unchanged; setup scripts tested manually on Windows,
same pattern as `setup-windows.ps1`).

**Manual test checklist:**

- [ ] Run `setup-chatgpt-windows.ps1` as Administrator — service installs and starts
- [ ] Browse to `http://127.0.0.1:8000/sse` — SSE stream response (not 404)
- [ ] Paste URL into ChatGPT Desktop Developer mode field
- [ ] Ask ChatGPT "List all libraries" — tools visible and respond correctly
- [ ] Reboot — service auto-starts, URL still works
- [ ] Run `uninstall-chatgpt-windows.ps1` — service removed, data dirs preserved

---

## Out of Scope

- TLS / HTTPS for the local SSE endpoint (loopback binding is sufficient)
- OAuth for the local service
- Standalone `.exe` build (can be added later — same PyInstaller approach as `build-windows.ps1`)
- macOS or Linux variants
- Changes to `src/mcpvectordb/`
