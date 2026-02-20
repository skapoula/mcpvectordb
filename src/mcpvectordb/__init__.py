"""mcpvectordb — MCP server for semantic search over a personal document library."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mcpvectordb")
except PackageNotFoundError:
    __version__ = "unknown"
