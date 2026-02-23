# End-to-End Test Cases — Claude Desktop Integration

Verify successful integration by pasting each **Prompt** verbatim into a new Claude Desktop conversation.
The server must be running and connected before starting (confirm with TC-01).

---

## TC-01 · Server connectivity

**Purpose:** Confirm the server started and connected.

**Prompt:**
> List all libraries.

**Pass criteria:**
- Claude calls `list_libraries` (visible in tool call disclosure)
- Returns an empty list (no error) — e.g. *"There are no libraries yet."*
- No error message mentioning connection failure, missing tool, or exception

---

## TC-02 · Ingest a local file

**Purpose:** Basic file ingestion pipeline (markitdown → embed → store).

**Pre-condition:** Have any small file at a known path, e.g. `C:\Users\you\Documents\test.pdf` (or a `.txt` file).

**Prompt:**
> Index the file at C:\Users\you\Documents\test.pdf

**Pass criteria:**
- Claude calls `ingest_file` with the correct path
- Response confirms `status: indexed`, returns a `doc_id` (UUID), and `chunk_count ≥ 1`
- No error about path not found, unsupported format, or embedding failure

---

## TC-03 · Ingest with tilde path

**Purpose:** Verify `~\` path expansion works on Windows.

**Prompt:**
> Index the file at ~\Documents\test.pdf

**Pass criteria:**
- Same as TC-02 — status `indexed` or `skipped` (if TC-02 already ran on same file)
- No "path not found" or "~ not expanded" error

---

## TC-04 · Deduplication — same file, same content

**Purpose:** Re-ingesting an unchanged file returns `skipped`, not a duplicate.

**Pre-condition:** TC-02 has already run.

**Prompt:**
> Index the file at C:\Users\you\Documents\test.pdf again.

**Pass criteria:**
- Claude calls `ingest_file`
- Response contains `status: skipped` (not `indexed` or `replaced`)
- Claude explains the file is already up to date

---

## TC-05 · List documents

**Purpose:** Confirm the document from TC-02 appears in the index.

**Prompt:**
> Show me all the documents you have indexed.

**Pass criteria:**
- Claude calls `list_documents`
- At least one document listed, showing the source path from TC-02
- Each document shows a `doc_id`, `title`, and `library`

---

## TC-06 · Semantic search

**Purpose:** Core retrieval — verify embedding and hybrid search work end-to-end.

**Pre-condition:** TC-02 completed successfully. Use any word or phrase you know appears in the test file.

**Prompt:**
> Search my documents for [a word or phrase from the test file].

**Pass criteria:**
- Claude calls `search`
- At least one result returned with a `content` excerpt containing or relating to the query term
- Source shows the file path from TC-02
- No "empty results" or embedding errors

---

## TC-07 · Search across a named library

**Purpose:** Verify library parameter routing.

**Prompt:**
> Index the file C:\Users\you\Documents\test.pdf into a library called "work", then search "work" for [same phrase as TC-06].

**Pass criteria:**
- First call: `ingest_file` with `library: work`, returns `status: indexed`
- Second call: `search` with `library: work`, returns results only from the "work" library
- `list_libraries` would now show both `default` and `work`

---

## TC-08 · List libraries (populated)

**Purpose:** Confirm library counts are accurate after ingestion.

**Prompt:**
> What libraries do I have and how many documents are in each?

**Pass criteria:**
- Claude calls `list_libraries`
- Shows at least the `default` library (and `work` if TC-07 ran)
- `document_count ≥ 1` for `default`
- `chunk_count ≥ 1` for each library

---

## TC-09 · Get full document text

**Purpose:** Verify full document reconstruction from chunks.

**Pre-condition:** Know a `doc_id` from TC-05 output.

**Prompt:**
> Show me the full text of the document with id [doc_id from TC-05].

**Pass criteria:**
- Claude calls `get_document`
- Returns multi-paragraph Markdown text of the original file
- `chunk_count` matches what was reported at ingest time

---

## TC-10 · Ingest a URL

**Purpose:** Verify URL fetching, HTML-to-Markdown conversion, and indexing.

**Prompt:**
> Index this URL into a library called "web": https://en.wikipedia.org/wiki/Vector_database

**Pass criteria:**
- Claude calls `ingest_url` with the URL and `library: web`
- Returns `status: indexed`, `chunk_count ≥ 5`
- No HTTP timeout or parse error

---

## TC-11 · Ingest direct text content

**Purpose:** Verify `ingest_content` for text that doesn't exist as a file on disk.

**Prompt:**
> Index the following note into a library called "notes", with source name "meeting-2026-02-23":
>
> "Decided to migrate the auth service to OAuth 2.0. Timeline: Q2 2026. Owner: platform team. Budget approved for new infrastructure."

**Pass criteria:**
- Claude calls `ingest_content` with the text, `source: meeting-2026-02-23`, `library: notes`
- Returns `status: indexed`, `chunk_count ≥ 1`

---

## TC-12 · Search returns correct library isolation

**Purpose:** Verify a search scoped to one library does not return results from another.

**Pre-condition:** TC-11 completed. The word "OAuth" exists only in `notes`.

**Prompt:**
> Search the "default" library for "OAuth".

**Pass criteria:**
- Claude calls `search` with `library: default`
- Returns 0 results (the OAuth content is in `notes`, not `default`)
- Claude confirms no relevant documents were found in that library

---

## TC-13 · Delete a document

**Purpose:** Verify delete removes all chunks and the document disappears from listing.

**Pre-condition:** Have a `doc_id` from any previous ingest.

**Prompt:**
> Delete the document with id [doc_id] from the index.

**Pass criteria:**
- Claude calls `delete_document`
- Returns `status: deleted`, `deleted_chunks ≥ 1`
- A follow-up `list_documents` call no longer shows that `doc_id`

---

## TC-14 · Search after delete

**Purpose:** Confirm deleted content is no longer retrievable.

**Pre-condition:** TC-13 completed. Know a term that was in the deleted document.

**Prompt:**
> Search all libraries for [term from the deleted document].

**Pass criteria:**
- Result set does not include any chunk with the deleted `doc_id`
- If no other document contained the term: 0 results returned, no error

---

## TC-15 · Unsupported file type

**Purpose:** Verify the server returns a clean error rather than crashing.

**Prompt:**
> Index the file C:\Users\you\Documents\test.xyz

**Pass criteria:**
- Claude calls `ingest_file`
- Returns `status: error` with a message mentioning unsupported format or extension
- Claude relays the error clearly — no unhandled exception, no crash, server still responsive

---

## TC-15b · Scanned / image-based PDF

**Purpose:** Verify a PDF with no extractable text returns a clear, actionable error — not a generic "chunking failed" message.

**Pre-condition:** Have a scanned PDF (image-only, no text layer) at a known path.

**Prompt:**
> Index the file C:\Users\you\Documents\scanned.pdf

**Pass criteria:**
- Returns `status: error` with a message indicating no text could be extracted
- Message suggests using `ingest_content` to pass the text directly
- No mention of "chunking failed"; no crash; server still responsive

---

## TC-16 · Non-existent file

**Purpose:** Verify a missing file path returns a useful error.

**Prompt:**
> Index the file C:\Users\you\Documents\does_not_exist.pdf

**Pass criteria:**
- Returns `status: error` with a message about the file not being found
- Server remains running — a follow-up "list all libraries" still works

---

## TC-17 · Search on empty index

**Purpose:** Edge case — verify empty result set, not an exception.

**Pre-condition:** Either a fresh install with nothing indexed, or after deleting all documents.

**Prompt:**
> Search my documents for "quantum entanglement".

**Pass criteria:**
- Returns 0 results
- Claude says something like *"I didn't find any relevant documents"* — no error, no crash

---

## TC-18 · Metadata round-trip

**Purpose:** Verify metadata attached at ingest is preserved and visible in results.

**Prompt:**
> Index C:\Users\you\Documents\test.pdf with metadata: author is "Alice", project is "Alpha".

**Pass criteria:**
- `ingest_file` called with `metadata: {"author": "Alice", "project": "Alpha"}`
- A `list_documents` or `get_document` call shows the metadata fields intact

---

## Execution checklist

Run in order. Each TC is independent unless a pre-condition is listed.

| TC | Tool exercised | Must pass before shipping |
|----|---------------|--------------------------|
| TC-01 | `list_libraries` | Yes — gate for all others |
| TC-02 | `ingest_file` | Yes |
| TC-03 | `ingest_file` (tilde path) | Yes — Windows-specific |
| TC-04 | `ingest_file` (dedup/skipped) | Yes |
| TC-05 | `list_documents` | Yes |
| TC-06 | `search` | Yes |
| TC-07 | `ingest_file` + `search` (library) | Yes |
| TC-08 | `list_libraries` (populated) | Yes |
| TC-09 | `get_document` | Yes |
| TC-10 | `ingest_url` | Yes |
| TC-11 | `ingest_content` | Yes |
| TC-12 | `search` (library isolation) | Yes |
| TC-13 | `delete_document` | Yes |
| TC-14 | `search` (post-delete) | Yes |
| TC-15 | error handling — bad extension | Yes |
| TC-16 | error handling — missing file | Yes |
| TC-17 | `search` on empty index | Nice to have |
| TC-18 | metadata round-trip | Nice to have |
