# mcpvectordb

Semantic search for your documents, available as a tool inside Claude Desktop.
Add files or web pages to your personal index, then ask Claude questions about them.

## How It Works

```mermaid
flowchart LR
    A[Your files or URLs] --> B[Server indexes content]
    B --> C[Ask Claude a question]
    C --> D[Relevant chunks returned]
```

mcpvectordb converts your files to text, splits them into searchable chunks, and stores
them locally — Claude queries the index to answer your questions.

## Getting Started

Install and connect the server to Claude Desktop before using any tools.
See [installation.md](./installation.md).

## How to Use It

### Ingest a local file

1. In a Claude Desktop conversation, ask Claude to index a file.
   Example: *"Index the file at /Users/alex/papers/attention.pdf into my research library."*
2. Claude calls `ingest_file` with the path and library name you specified.
3. Wait for the confirmation: `"status": "indexed"` with a chunk count.
4. The document is now searchable.

### Ingest a web page

1. Ask Claude to index a URL.
   Example: *"Add https://lancedb.github.io/lancedb/ to my references library."*
2. Claude calls `ingest_url`, fetches the page, and indexes its content.
3. Confirm the `"status": "indexed"` response before searching.

### Search your documents

1. Ask Claude a question about your indexed content.
   Example: *"What does my research library say about attention mechanisms?"*
2. Claude calls `search` and retrieves the most relevant chunks.
3. Claude answers using those chunks and can cite the source file and page.

### Manage your index

- **List documents:** *"Show me what's in my research library."* → `list_documents`
- **List libraries:** *"What libraries do I have?"* → `list_libraries`
- **Remove a document:** *"Delete the attention.pdf document."* → `delete_document`
- **Read a document:** *"Show me the full text of doc id abc-123."* → `get_document`

## Common Issues

| Symptom | Fix |
|---|---|
| File format not accepted | Check the supported formats: PDF, DOCX, PPTX, XLSX, HTML, TXT, MD, CSV, JSON, XML, images, audio, ZIP |
| Search returns empty results | Confirm the document was ingested — use `list_documents` to verify |
| Claude Desktop shows no tools | Restart Claude Desktop after editing the config JSON |
| Results look wrong after a config change | If `EMBEDDING_MODEL` was changed, all documents must be re-indexed |
| Logs not visible | Set `LOG_FILE=~/.mcpvectordb/server.log` in your `.env` file |

## Getting Help

Open an issue at the project repository or check [contributing.md](./contributing.md)
for developer setup instructions.
