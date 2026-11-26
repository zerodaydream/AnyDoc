from functools import lru_cache

from backend.core.config import get_settings
from backend.llm.base import LLMProvider


@lru_cache
def get_llm() -> LLMProvider:
    s = get_settings()
    providers: dict[str, LLMProvider] = {}
    if s.llm_provider != "fake" and s.gemini_api_key:
        from backend.llm.providers.gemini.provider import GeminiProvider

        providers["gemini"] = GeminiProvider(s.gemini_api_key, s.llm_answer_model, s.llm_fast_model, s.llm_timeout_s)
    if s.llm_provider != "fake" and s.groq_api_key:
        from backend.llm.providers.groq.provider import GroqProvider

        providers["groq"] = GroqProvider(s.groq_api_key, s.groq_answer_model, s.groq_fast_model, s.llm_timeout_s)
    if not providers:
        from backend.llm.providers.fake import FakeProvider

        return FakeProvider()
    from backend.llm.router import RoutedProvider

    return RoutedProvider(providers, s.provider_for, s.default_model)
