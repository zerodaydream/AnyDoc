"""Tavily Search API (D13): built for LLM use; returns cleaned page chunks with relevance scores.

Free plan: 1,000 credits a month, no card; a basic search costs 1 credit (docs.tavily.com, read 2026-11-28).
"""

import logging
from urllib.parse import urlparse

import httpx

from backend.websearch.base import SearchHit, SearchUnavailable

log = logging.getLogger(__name__)
URL = "https://api.tavily.com/search"


class TavilySearch:
    name = "Tavily"

    def __init__(self, api_key: str, timeout_s: float, client: httpx.AsyncClient | None = None) -> None:
        self._key, self._timeout, self._client = api_key, timeout_s, client

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        body = {
            "query": query,
            "search_depth": "basic",  # 1 credit; up to 3 chunks of ~500 chars per source
            "chunks_per_source": 3,
            "max_results": max_results,
            "include_answer": False,  # the answer is written by our model from the sources, and checked
            "include_raw_content": False,
        }
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            r = await client.post(URL, json=body, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as e:
            log.warning("tavily_failed", extra={"error": type(e).__name__})
            raise SearchUnavailable("Web search couldn't be reached.") from e
        finally:
            if self._client is None:
                await client.aclose()
        if r.status_code == 401:
            raise SearchUnavailable("The Tavily API key is missing or invalid.")
        if r.status_code in (429, 432, 433):
            raise SearchUnavailable("Web search quota is used up for now.")
        if r.status_code != 200:
            log.warning("tavily_failed", extra={"code": r.status_code})
            raise SearchUnavailable(f"Web search failed ({r.status_code}).")
        hits = []
        for x in r.json().get("results") or []:
            url = str(x.get("url") or "")
            if not url.startswith(("https://", "http://")) or not x.get("content"):
                continue
            score = x.get("score")
            hits.append(
                SearchHit(
                    title=str(x.get("title") or urlparse(url).netloc),
                    url=url,
                    domain=urlparse(url).netloc.removeprefix("www."),
                    content=str(x["content"]),
                    score=float(score) if isinstance(score, int | float) else None,
                )
            )
        return hits
