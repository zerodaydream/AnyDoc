"""Web search as a tool the answer model can ask for (via `web_query`). Engines are swappable; see factory.py."""

from dataclasses import dataclass
from typing import Protocol


class SearchUnavailable(Exception):
    """The search itself failed (quota, outage, blocked). The document answer still stands."""


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    domain: str
    content: str  # the text the engine gives for this page (snippet or extracted chunks): untrusted data
    score: float | None = None  # engine's relevance score, when it has one


class WebSearch(Protocol):
    name: str  # shown to readers: "Tavily", "DuckDuckGo (ddgs)"

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        """Hits for `query`, best first. [] means nothing found; raises SearchUnavailable when the search failed."""
        ...
