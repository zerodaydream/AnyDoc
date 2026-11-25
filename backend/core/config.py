import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, PydanticBaseSettingsSource, SettingsConfigDict

THINKING_ORDER = ["minimal", "low", "medium", "high", "xhigh"]


def clamp_level(level: str, supported: list[str]) -> str:
    """Nearest supported level (minimal -> low, xhigh -> high); ties go to the cheaper level."""
    if level in supported or not supported:
        return level
    i = THINKING_ORDER.index(level) if level in THINKING_ORDER else 2
    return min(supported, key=lambda s: (abs(THINKING_ORDER.index(s) - i), THINKING_ORDER.index(s)))


class Settings(BaseSettings):
    # ANYDOC_ENV_FILE="" disables the file (tests). Production has no .env, so real env vars apply.
    model_config = SettingsConfigDict(env_file=os.environ.get("ANYDOC_ENV_FILE", ".env") or None, extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Owner decision: .env is the source of truth locally; a stray shell export must not override it.
        return init_settings, dotenv_settings, env_settings, file_secret_settings

    app_env: str = "local"
    data_dir: Path = Path("./var/data")
    database_url: str = "postgresql+psycopg://anydoc:anydoc@localhost:5432/anydoc"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]  # comma-separated in env

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
    # User-selectable options (comma-separated in .env). The answer model is the default and is always allowed.
    llm_models: Annotated[list[str], NoDecode] = []
    llm_thinking_levels: Annotated[list[str], NoDecode] = ["minimal", "low", "medium", "high", "xhigh"]
    llm_thinking_default: str = "medium"
    # Per-model levels, JSON: {"model": "low,medium,high*"} ("*" marks that model's default). Unlisted models get
    # all LLM_THINKING_LEVELS and LLM_THINKING_DEFAULT.
    llm_model_thinking: dict[str, str] = {}
    max_question_chars: int = 4000
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

    @field_validator("cors_origins", "llm_models", "llm_thinking_levels", mode="before")
    @classmethod
    def _split_list(cls, v: object) -> object:
        return [o.strip() for o in v.split(",") if o.strip()] if isinstance(v, str) else v

    @property
    def allowed_models(self) -> list[str]:
        return list(dict.fromkeys([self.llm_answer_model, *self.llm_models]))

    @property
    def thinking_levels(self) -> list[str]:
        return [lvl.lower() for lvl in self.llm_thinking_levels]

    def thinking_for(self, model: str) -> tuple[list[str], str]:
        """(levels this model accepts, its default), in canonical order and within LLM_THINKING_LEVELS."""
        spec = self.llm_model_thinking.get(model)
        if spec is None:
            levels, default = self.thinking_levels, self.llm_thinking_default.lower()
        else:
            items = [x.strip().lower() for x in spec.split(",") if x.strip()]
            levels = [x.rstrip("*") for x in items]
            default = next((x.rstrip("*") for x in items if x.endswith("*")), self.llm_thinking_default.lower())
        levels = [lv for lv in THINKING_ORDER if lv in levels and lv in self.thinking_levels]
        return levels, (default if default in levels else clamp_level(default, levels))

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
