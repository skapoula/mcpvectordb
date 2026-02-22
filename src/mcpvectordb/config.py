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
    embedding_model: str = "nomic-ai/nomic-embed-text-v1.5"
    embedding_batch_size: int = 32
    # Must match EMBEDDING_MODEL output size; changing requires full re-index
    embedding_dimension: int = 768

    # Search
    hybrid_search_enabled: bool = True  # BM25 + vector; disable for pure vector mode
    search_refine_factor: int = 10  # re-rank top N*refine_factor exact results for recall

    # Chunking
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64
    chunk_min_tokens: int = 50

    # Upload
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MB; controls Starlette max_part_size

    # Security — extra allowed Host headers for DNS rebinding protection.
    # Comma-separated. Add your reverse-proxy / tunnel hostname when running behind
    # tailscale serve, nginx, cloudflared, etc.
    # e.g.  ALLOWED_HOSTS=pluto.tailbcd62a.ts.net
    #        ALLOWED_HOSTS=host1.example.com,host2.example.com
    # pydantic-settings would JSON-parse a list[str] field before any validator runs,
    # so we store the raw string and split it ourselves.
    allowed_hosts: str = ""

    @property
    def allowed_hosts_list(self) -> list[str]:
        """Return allowed_hosts as a list, split on commas."""
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    # URL fetching
    http_timeout_seconds: float = 10.0
    http_user_agent: str = "mcpvectordb/1.0"

    # Logging
    log_level: str = "INFO"
    log_file: str | None = None


settings = Settings()
