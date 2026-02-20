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
