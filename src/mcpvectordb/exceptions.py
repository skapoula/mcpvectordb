"""Domain exception classes for mcpvectordb."""


class UnsupportedFormatError(Exception):
    """Raised when a file extension or MIME type is not supported by the converter."""


class IngestionError(Exception):
    """Raised when the ingestion pipeline fails (fetch, conversion, or store write)."""


class StoreError(Exception):
    """Raised when a LanceDB read or write operation fails."""


class EmbeddingError(Exception):
    """Raised when the embedding model fails to produce vectors."""
