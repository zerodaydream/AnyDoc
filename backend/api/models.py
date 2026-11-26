"""Model + thinking options for the composer. Lists come from backend/config.json (MODELS_ENABLED); limits from the provider (no generation)."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.core.config import get_settings
from backend.llm.factory import get_llm

router = APIRouter(prefix="/api/models", tags=["models"])


class ModelsOut(BaseModel):
    models: list[dict[str, Any]]
    default_model: str
    thinking_levels: list[str]
    default_thinking: str
    max_question_chars: int


@router.get("")
async def list_models() -> ModelsOut:
    s = get_settings()
    models = await get_llm().describe_models(s.allowed_models)
    for meta in models:
        levels, default = s.thinking_for(meta["id"])
        meta["thinking_levels"] = levels if meta["thinking"] else []
        meta["default_thinking"] = default if meta["thinking"] else None
    return ModelsOut(
        models=models,
        default_model=s.llm_answer_model,
        thinking_levels=s.thinking_levels,
        default_thinking=s.llm_thinking_default.lower(),
        max_question_chars=s.max_question_chars,
    )
