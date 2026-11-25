from functools import lru_cache
from pathlib import Path
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    data_dir: Path = Path("./var/data")
    database_url: str = "postgresql+psycopg://anydoc:anydoc@localhost:5432/anydoc"
    cors_origins: list[str] = ["http://localhost:5173"]

    local_owner_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    local_workspace_id: UUID = UUID("00000000-0000-0000-0000-000000000001")

    max_upload_mb: int = 100
    max_pages: int = 500
    parse_timeout_s: int = 120
    parse_memory_mb: int = 1024
    worker_concurrency: int = 2

    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    llm_answer_model: str = "gemini-3.8-flash"
    llm_fast_model: str = "gemini-3.5-flash-lite"
    llm_timeout_s: float = 120.0
    full_context_token_budget: int = 120_000
    retrieval_top_k: int = 8
    quote_fuzzy_min: float = Field(90.0, ge=50, le=100)
    history_turns: int = 6

    embed_provider: str = "local"
    embed_model: str = "microsoft/harrier-oss-v1-270m"
    embed_dim: int = 640
    embed_device: str = "auto"
    embed_batch_size: int = 16

    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "anydoc-local"
    trace_content: bool = False

    @property
    def psycopg_dsn(self) -> str:
        """Plain libpq DSN for procrastinate/psycopg (no SQLAlchemy driver suffix)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
