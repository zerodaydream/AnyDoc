import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, NoDecode, PydanticBaseSettingsSource, SettingsConfigDict

THINKING_ORDER = ["minimal", "low", "medium", "high", "xhigh"]


def clamp_level(level: str, supported: list[str]) -> str:
    """Nearest supported level (minimal -> low, xhigh -> high); ties go to the cheaper level."""
    if level in supported or not supported:
        return level
    i = THINKING_ORDER.index(level) if level in THINKING_ORDER else 2
    return min(supported, key=lambda s: (abs(THINKING_ORDER.index(s) - i), THINKING_ORDER.index(s)))


# Non-secret product settings (models, feature flags, limits). Secrets and machine-specific values stay in .env.
_CONFIG_JSON = Path(__file__).resolve().parents[1] / "config.json"


class JsonConfigSource(PydanticBaseSettingsSource):
    """`backend/config.json`, keys in env-var style (`APP_ENV`). ANYDOC_CONFIG_FILE="" disables it (tests)."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        path = os.environ.get("ANYDOC_CONFIG_FILE", str(_CONFIG_JSON))
        raw = json.loads(Path(path).read_text(encoding="utf-8")) if path and Path(path).is_file() else {}
        self._data = {k.lower(): v for k, v in raw.items() if k.lower() in settings_cls.model_fields}

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(self._data)


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
        # backend/config.json comes after both, so a deployment can still override any key with an env var.
        return init_settings, dotenv_settings, env_settings, JsonConfigSource(settings_cls), file_secret_settings

    app_env: str = "local"
    data_dir: Path = Path("./var/data")
    database_url: str = "postgresql+psycopg://anydoc:anydoc@localhost:5432/anydoc"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]  # comma-separated in env

    local_owner_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    local_workspace_id: UUID = UUID("00000000-0000-0000-0000-000000000001")

    max_upload_mb: int = 100
    max_pages: int = 500
    max_text_chars: int = 2_000_000  # TXT/MD: roughly 500 pages of prose
    parse_timeout_s: int = 120
    parse_memory_mb: int = 1024
    query_timeout_s: int = 30  # one table query plan (CSV), run in the parsing sandbox
    worker_concurrency: int = 2

    llm_provider: str = "gemini"  # default picker tab: gemini | groq; "fake" forces the offline model
    gemini_api_key: str = ""
    groq_api_key: str = ""
    llm_answer_model: str = "gemini-3.8-flash"
    llm_fast_model: str = "gemini-3.5-flash-lite"
    llm_timeout_s: float = 120.0
    # Models users may pick, with their thinking levels: {"model": "low,medium,high*"} ("*" marks that model's
    # default; "off*" makes no thinking the default). The answer model is the default and is always allowed.
    models_enabled: dict[str, str] = {}
    llm_thinking_levels: Annotated[list[str], NoDecode] = ["minimal", "low", "medium", "high", "xhigh"]
    llm_thinking_default: str = "medium"  # for a model not in MODELS_ENABLED (or listed without a "*")
    # Groq models (direct answers, no thinking), offered on the picker's Groq tab when GROQ_API_KEY is set.
    groq_answer_model: str = "qwen/qwen3.8-27b"
    groq_fast_model: str = "qwen/qwen3.8-27b"
    groq_models_enabled: dict[str, str] = {}
    # Document tokens per Groq answer. The free plan caps input at 7,000 tokens a minute (measured 2026-11-27); this
    # leaves room for instructions, schema, question and history.
    groq_context_token_budget: int = 4000
    max_question_chars: int = 4000
    full_context_token_budget: int = 120_000
    retrieval_top_k: int = 8
    quote_fuzzy_min: float = Field(90.0, ge=50, le=100)
    history_turns: int = 6
    # Web lookup when the document can't answer: the answer model asks for it with `web_query`, a search engine runs
    # it (backend/websearch/), and a second call answers only from the hits, quoting them. Sends the search query
    # (never document text) to the engine; off unless config.json or env turns it on.
    web_search_enabled: bool = False
    web_search_provider: str = "auto"  # auto (Tavily with a key, else ddgs) | tavily | ddgs
    tavily_api_key: str = ""
    web_search_max_results: int = 5
    web_search_timeout_s: float = 15.0

    embed_provider: str = "local"
    embed_model: str = "microsoft/harrier-oss-v1-270m"
    embed_dim: int = 640
    embed_device: str = "auto"
    embed_batch_size: int = 16

    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "anydoc-local"
    trace_content: bool = False

    @field_validator("cors_origins", "llm_thinking_levels", mode="before")
    @classmethod
    def _split_list(cls, v: object) -> object:
        return [o.strip() for o in v.split(",") if o.strip()] if isinstance(v, str) else v

    @property
    def providers(self) -> list[str]:
        """LLM providers in the model picker: those with a key. With no key (or LLM_PROVIDER=fake) the offline fake
        model answers for the Gemini list."""
        keys = {"gemini": self.gemini_api_key, "groq": self.groq_api_key}
        on = [p for p, key in keys.items() if key] if self.llm_provider != "fake" else []
        return on or ["gemini"]

    def provider_for(self, model: str) -> str:
        groq = {self.groq_answer_model, self.groq_fast_model, *self.groq_models_enabled}
        return "groq" if model in groq else "gemini"

    def models_for(self, provider: str) -> list[str]:
        """The provider's models, its answer model first. Groq's live in separate keys because dict settings from
        .env merge into config.json's instead of replacing them."""
        if provider == "groq":
            return list(dict.fromkeys([self.groq_answer_model, *self.groq_models_enabled]))
        return list(dict.fromkeys([self.llm_answer_model, *self.models_enabled]))

    @property
    def default_model(self) -> str:
        """LLM_PROVIDER picks the default tab; its answer model is the default model."""
        return self.models_for(self.llm_provider if self.llm_provider in self.providers else self.providers[0])[0]

    def context_budget(self, model: str) -> int:
        """Document tokens one answer may send to this model's provider."""
        return self.groq_context_token_budget if self.provider_for(model) == "groq" else self.full_context_token_budget

    @property
    def allowed_models(self) -> list[str]:
        return [m for p in self.providers for m in self.models_for(p)]

    @property
    def thinking_levels(self) -> list[str]:
        return [lvl.lower() for lvl in self.llm_thinking_levels]

    def thinking_for(self, model: str) -> tuple[list[str], str]:
        """(levels this model accepts, its default), in canonical order and within LLM_THINKING_LEVELS."""
        spec = (
            self.groq_models_enabled.get(model, "")
            if self.provider_for(model) == "groq"
            else self.models_enabled.get(model)
        )
        if spec is None:
            levels, default = self.thinking_levels, self.llm_thinking_default.lower()
        else:
            items = [x.strip().lower() for x in spec.split(",") if x.strip()]
            levels = [x.rstrip("*") for x in items]
            default = next((x.rstrip("*") for x in items if x.endswith("*")), self.llm_thinking_default.lower())
        levels = [lv for lv in THINKING_ORDER if lv in levels and lv in self.thinking_levels]
        return levels, (default if default in levels or default == "off" else clamp_level(default, levels))

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
