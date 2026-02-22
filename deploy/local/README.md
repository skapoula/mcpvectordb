# Local Container Deployment

Run mcpvectordb as a persistent container on the same machine as Claude Desktop.
Claude Desktop connects via `http://localhost:8000/mcp` instead of spawning a subprocess,
so the embedding model stays loaded between sessions and the server lifecycle is independent
of Claude Desktop.

## When to Use This Mode

| Mode | Best for | Lifecycle |
|------|----------|-----------|
| **stdio subprocess** | Simple local use; no Docker required | Restarts with Claude Desktop; embedding model reloads each time |
| **Local container (this guide)** | Persistent server on same machine; faster after first load | Independent of Claude Desktop; survives restarts via Docker |
| **Remote / k3s** | Server on a different machine; shared by multiple clients | See `deploy/k3s/` or `deploy/tailscale/` |

## Prerequisites

- **macOS / Windows:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) 4.0 or later
- **Linux:** Docker Engine 20.10+ (`docker compose` plugin) or Podman 4.0+ with `podman-compose`

## Step 1: Build the Image

Run from the **project root** (where `Dockerfile` lives):

```bash
docker build -t mcpvectordb:0.1.0 .
```

First build downloads the embedding model (~270 MB) and installs Python dependencies.
Subsequent builds use the layer cache and are fast.

## Step 2: Start the Container

```bash
docker compose -f deploy/local/docker-compose.yml up -d
```

The container binds to `127.0.0.1:8000` only — not accessible from other machines on your network.

**Optional — mount a documents folder for `ingest_file`:**

macOS / Linux:
```bash
DOCS_DIR=/path/to/your/docs docker compose -f deploy/local/docker-compose.yml up -d
```

Windows (PowerShell):
```powershell
$env:DOCS_DIR = "C:\Users\<you>\Documents"; docker compose -f deploy/local/docker-compose.yml up -d
```

Files under `DOCS_DIR` are available inside the container at `/data/docs/`. Pass the
container path to `ingest_file`, e.g. `/data/docs/report.pdf`. For HTTP-mode ingestion
without path mapping, use `POST /upload` instead.

## Step 3: Verify the Container Is Running

```bash
# Check status
docker compose -f deploy/local/docker-compose.yml ps

# Follow startup logs (Ctrl+C to stop)
docker compose -f deploy/local/docker-compose.yml logs -f

# Confirm the server responds
curl http://localhost:8000/
```

Expected: HTTP 200 with a short JSON response. The embedding model loads on first use,
so the initial search or ingest will take a few extra seconds.

## Step 4: Configure Claude Desktop

Copy `deploy/local/claude_desktop_config.example.json` as a reference, then edit your
Claude Desktop config to add or merge the `mcpvectordb` entry:

```json
{
  "mcpServers": {
    "mcpvectordb": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

Config file locations:

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

Restart Claude Desktop. Open a new conversation and ask:
*"List my mcpvectordb libraries."*

Expected response: `{ "libraries": [] }` — connected and ready.

## Step 5: Auto-Start on Boot

### macOS and Windows

Docker Desktop starts automatically at login. Because the Compose file sets
`restart: unless-stopped`, the container restarts with the Docker daemon — no extra
configuration needed.

### Linux — Docker Engine

Enable the Docker daemon to start on boot (one-time):

```bash
sudo systemctl enable docker
```

The `restart: unless-stopped` policy handles the rest.

### Linux — Podman (rootless)

Podman uses systemd user units instead of a daemon policy:

```bash
# Generate the unit file (run after first `podman compose up -d`)
podman generate systemd --name mcpvectordb-mcpvectordb-1 --new \
  > ~/.config/systemd/user/mcpvectordb.service

# Enable and start the unit
systemctl --user enable --now mcpvectordb

# Allow the unit to run after logout (required for headless / server use)
loginctl enable-linger $USER
```

## Updating

Rebuild the image after pulling new code, then restart the container:

```bash
docker build -t mcpvectordb:0.1.0 .
docker compose -f deploy/local/docker-compose.yml up -d
```

The named volume `lancedb-data` is preserved — your indexed documents are not affected.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `curl: (7) Failed to connect to localhost port 8000` | Container not running | `docker compose -f deploy/local/docker-compose.yml up -d`; check `logs -f` |
| Claude Desktop shows "MCP server not found" | Wrong config path or typo in `url` | Check config file location for your OS; confirm `"url": "http://localhost:8000/mcp"` |
| Port 8000 already in use | Another process bound to 8000 | Stop the conflicting process or change `MCP_PORT` in `.env` and update the ports mapping |
| Slow first response after start | Embedding model loading | Wait ~10–30 s; subsequent requests are fast |
| `ingest_file` returns "file not found" | Path is host path, not container path | Mount with `DOCS_DIR` and use `/data/docs/<filename>` inside the container |
| Container exits immediately | Missing `Dockerfile` or build error | Run `docker build -t mcpvectordb:0.1.0 .` from project root and check output |
