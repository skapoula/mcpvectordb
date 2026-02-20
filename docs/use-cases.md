# Use Cases

## Use Case 1: Index a research paper and ask questions about it

**The situation:** You have a PDF research paper on your laptop and want to ask Claude
detailed questions about its content without pasting the whole text.

**Input:** You tell Claude: *"Index /Users/alex/papers/attention-is-all-you-need.pdf
into my research library."*

**What happens:** mcpvectordb converts the PDF to Markdown, splits it into 512-token
chunks, embeds each chunk, and stores them in your local LanceDB index under the
`research` library.

**Output:** Claude confirms: `status: "indexed"`, `chunk_count: 18`, `library: "research"`.
When you then ask *"What architecture does the paper use for the encoder?"*, Claude
calls `search` and returns the 5 most relevant chunks — each showing the source file,
page number, and matching text — and answers your question with citations.

---

### Try It

1. Ask Claude: *"Index /path/to/paper.pdf into library research."*
2. Wait for the `"status": "indexed"` confirmation.
3. Ask Claude: *"What does my research library say about [your topic]?"*

---

## Use Case 2: Index a documentation page and search it offline

**The situation:** You want to reference LanceDB's Python API documentation while
working offline, without switching browser tabs.

**Input:** You tell Claude: *"Add https://lancedb.github.io/lancedb/python/python.html
to my references library."*

**What happens:** mcpvectordb fetches the page, converts the HTML to Markdown, chunks
and embeds it, and stores it under the `references` library. The page is now available
for search even when you have no internet connection.

**Output:** Claude confirms: `status: "indexed"`, `chunk_count: 34`, `library: "references"`.
When you ask *"How do I create a scalar index in LanceDB?"*, Claude returns the 5
most relevant text sections from that page, including the exact method name and
code examples from the documentation.

---

### Try It

1. Ask Claude: *"Index https://example.com/docs/page into library references."*
2. Wait for the `"status": "indexed"` confirmation.
3. Ask Claude: *"What does my references library say about [your topic]?"*
