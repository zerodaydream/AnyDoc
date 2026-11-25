from functools import lru_cache

from backend.core.config import get_settings
from backend.llm.base import LLMProvider


@lru_cache
def get_llm() -> LLMProvider:
    s = get_settings()
    if s.llm_provider == "fake" or not s.gemini_api_key:
        from backend.llm.providers.fake import FakeProvider

        return FakeProvider()
    from backend.llm.providers.gemini.provider import GeminiProvider

    return GeminiProvider(s.gemini_api_key, s.llm_answer_model, s.llm_fast_model, s.llm_timeout_s)
