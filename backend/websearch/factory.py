from functools import lru_cache

from backend.core.config import get_settings
from backend.websearch.base import WebSearch
from backend.websearch.ddgs_engine import DdgsSearch
from backend.websearch.tavily import TavilySearch


@lru_cache
def get_web_search() -> WebSearch:
    """WEB_SEARCH_PROVIDER: "auto" (Tavily when TAVILY_API_KEY is set, else ddgs), "tavily" or "ddgs"."""
    s = get_settings()
    choice = s.web_search_provider
    if choice == "auto":
        choice = "tavily" if s.tavily_api_key else "ddgs"
    if choice == "tavily":
        if not s.tavily_api_key:
            raise RuntimeError("WEB_SEARCH_PROVIDER=tavily needs TAVILY_API_KEY.")
        return TavilySearch(s.tavily_api_key, s.web_search_timeout_s)
    if choice == "ddgs":
        return DdgsSearch(s.web_search_timeout_s)
    raise RuntimeError(f"Unknown WEB_SEARCH_PROVIDER {choice!r}: use auto, tavily or ddgs.")
