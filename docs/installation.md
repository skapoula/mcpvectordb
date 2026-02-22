# Installation

## Requirements

- Python 3.11 or later
- [`uv`](https://docs.astral.sh/uv/) (recommended) or pip
- Claude Desktop (for local stdio mode)
- kubectl + a k3s cluster (for hosted SSE mode only)

## Option A: Local stdio (recommended)

Claude Desktop runs mcpvectordb as a subprocess. All data stays on your machine.

1. Clone the repository:

```bash
git clone <repo-url> mcpvectordb
cd mcpvectordb
```

2. Install dependencies:

```bash
uv sync
```

3. Copy the example config and set your database path:

```bash
cp .env.example .env
```

4. Edit `.env` — set `LANCEDB_URI` to a local directory (e.g. `~/.mcpvectordb/lancedb`).

5. Add the server to Claude Desktop's config
   (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "mcpvectordb": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/mcpvectordb", "mcpvectordb"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "LANCEDB_URI": "/Users/<you>/.mcpvectordb/lancedb"
      }
    }
  }
}
```

6. Restart Claude Desktop.

## Option B: Hosted SSE (k3s)

Claude Desktop connects to the server over HTTP. Data is stored on a PersistentVolume.

1. Build the container image and push to your registry.

2. Apply the k3s manifests:

```bash
kubectl apply -f deploy/k3s/pvc.yaml
kubectl apply -f deploy/k3s/deployment.yaml
kubectl apply -f deploy/k3s/service.yaml
```

3. Add the server URL to Claude Desktop's config:

```json
{
  "mcpServers": {
    "mcpvectordb": {
      "url": "http://<cluster-ip>:8000/sse"
    }
  }
}
```

## Option C: Local Container HTTP (persistent, same machine)

The container runs on the same machine as Claude Desktop and listens on
`http://localhost:8000`. Claude Desktop connects via URL rather than spawning
a subprocess. Data is stored in a Docker named volume and survives restarts.

**Use this when:** you want a persistent server that stays running between Claude
Desktop sessions, with better process isolation than Option A.

**Requires:** Docker Desktop (macOS/Windows) or Docker Engine/Podman (Linux).

1. Build the image (from the project root):

```bash
docker build -t mcpvectordb:0.1.0 .
```

2. Start the container:

```bash
docker compose -f deploy/local/docker-compose.yml up -d
```

3. Add the server to Claude Desktop's config:

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
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

4. Restart Claude Desktop.

For auto-start on boot and Linux Podman rootless setup, see
[`deploy/local/README.md`](../deploy/local/README.md).

## Verify It's Working

After restarting Claude Desktop, open a new conversation and ask:
*"List my mcpvectordb libraries."*

Expected response:

```json
{ "libraries": [] }
```

An empty list means the server is connected and the database is ready.

## Uninstall

1. Remove the `mcpvectordb` entry from Claude Desktop's config and restart Claude Desktop.
2. Delete the LanceDB data directory: `rm -rf ~/.mcpvectordb/` (local mode only).
