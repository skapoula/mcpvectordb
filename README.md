# mcpvectordb

MCP server that gives Claude Desktop semantic search over a personal document library.
Ingest local files or web pages — search them with natural language from any Claude Desktop conversation.

Supports PDF, Word, PowerPoint, Excel, HTML, images (OCR), audio (transcription), CSV,
JSON, and more via [MarkItDown](https://github.com/microsoft/markitdown). Vectors are
stored in [LanceDB](https://lancedb.github.io/lancedb/) — no external database required.

## Documentation

See [docs/README.md](docs/README.md) for the full guide index.

## Quick Start

1. Install dependencies:

```bash
uv sync
```

2. Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "mcpvectordb": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcpvectordb", "mcpvectordb"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "LANCEDB_URI": "/Users/<you>/.mcpvectordb/lancedb"
      }
    }
  }
}
```

3. Restart Claude Desktop. The `ingest_file`, `ingest_url`, and `search` tools will appear.

For full setup options (including k3s/SSE hosting), see [docs/installation.md](docs/installation.md).
