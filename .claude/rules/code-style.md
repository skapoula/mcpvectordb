# Code Style — mcpvectordb
# Extends /workspace/.claude/rules/master-code-style.md (loaded automatically).
# Only project-specific additions and overrides are listed here.

## Data Structures

- Use **Pydantic models** for all data that crosses a module boundary
  (function return values, MCP tool inputs/outputs, config, LanceDB records).
- Use `dataclasses` only for simple internal structs with no validation.
- Never pass raw `dict` objects across module boundaries — define a model.
- Use `pydantic.Field` with a `description=` for every field on MCP-facing models;
  Claude Desktop uses these descriptions to understand the tool schema.

## Async

- `server.py` and `transport.py` are async (MCP SDK is async).
- All I/O-bound operations (LanceDB reads/writes, HTTP fetches, file reads) must be
  `async` or run in a thread pool via `asyncio.to_thread()` — never block the event loop.
- Use `asyncio.to_thread()` for blocking calls in libraries that don't support async
  (e.g. sentence-transformers, markitdown, synchronous LanceDB operations).
- Do not mix sync and async code in the same function.

## stdio Transport

- CRITICAL: In `stdio` transport mode, ALL output must go to `stderr` or a log file.
  A single byte on `stdout` outside the MCP protocol will silently break Claude Desktop.
- Never use `print()` anywhere in `src/` — `logging` to `stderr` only.

## Error Handling (additions)

- MCP tool handlers must catch all exceptions and return structured error responses
  rather than letting exceptions propagate to the MCP framework unhandled.
- Domain exception classes live in `exceptions.py`:
  `UnsupportedFormatError`, `IngestionError`, `StoreError`, `EmbeddingError`.
