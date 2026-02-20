"""Runtime configuration loaded from environment variables via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime settings for mcpvectordb.

    Values are loaded from environment variables or a .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Transport
    mcp_transport: str = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000

    # LanceDB
    lancedb_uri: str = "~/.mcpvectordb/lancedb"
    lancedb_table_name: str = "documents"
    default_library: str = "default"

    # Embedding
    embedding_model: str = "nomic-embed-text-v1.5"
    embedding_batch_size: int = 32

    # Chunking
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64
    chunk_min_tokens: int = 50

    # URL fetching
    http_timeout_seconds: float = 10.0
    http_user_agent: str = "mcpvectordb/1.0"

    # Logging
    log_level: str = "INFO"
    log_file: str | None = None


settings = Settings()
