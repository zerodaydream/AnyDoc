"""Keyless web search through `ddgs` (MIT), a metasearch library that reads search engines' result pages.

Free and needs no account, but unofficial: engines throttle it, and in a measured run most queries came back empty
(D13). Fine for local use; a hosted deployment should set TAVILY_API_KEY (or another API) instead.
"""

import asyncio
import logging
from urllib.parse import urlparse

from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from backend.websearch.base import SearchHit, SearchUnavailable

log = logging.getLogger(__name__)


class DdgsSearch:
    name = "DuckDuckGo (ddgs)"

    def __init__(self, timeout_s: float, backend: str = "auto") -> None:
        self._timeout, self._backend = timeout_s, backend

    def _run(self, query: str, max_results: int) -> list[dict[str, str]]:
        return DDGS(timeout=int(self._timeout)).text(query, max_results=max_results, backend=self._backend)

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        try:
            rows = await asyncio.wait_for(asyncio.to_thread(self._run, query, max_results), self._timeout + 5)
        except (RatelimitException, TimeoutException, TimeoutError) as e:
            log.warning("ddgs_failed", extra={"error": type(e).__name__})
            raise SearchUnavailable("Web search is busy right now. Try again in a moment.") from e
        except DDGSException as e:
            if "no results" in str(e).lower():  # also what a throttled engine answers
                return []
            log.warning("ddgs_failed", extra={"error": type(e).__name__})
            raise SearchUnavailable("Web search failed.") from e
        hits, seen = [], set()
        for x in rows:
            url = str(x.get("href") or "")
            if not url.startswith(("https://", "http://")) or url in seen or not x.get("body"):
                continue
            seen.add(url)
            domain = urlparse(url).netloc.removeprefix("www.")
            hits.append(SearchHit(title=str(x.get("title") or domain), url=url, domain=domain, content=str(x["body"])))
        return hits
