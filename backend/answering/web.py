"""Web lookup for questions the document can't answer (D13). Provider-independent: works for Gemini and Groq.

The answer model asks for it by filling `web_query` (or by abstaining). A search engine runs the query
(backend/websearch/), then one structured call answers from the numbered hits only, quoting them. Each segment is
kept only if a quote is found in the source it names and every number in it appears in those sources: the same
rules as document citations. The result is shown apart from the document answer and never becomes a citation.
"""

import logging
import time
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from backend.core.config import get_settings
from backend.grounding.validator import match_quote, numbers_in
from backend.llm.base import LLMProvider, WebResult, WebSegment, WebSource
from backend.llm.prompts import WEB_SYSTEM, build_web_prompt
from backend.observability.tracing import trace_metadata, traced
from backend.websearch.base import SearchHit, SearchUnavailable, WebSearch

log = logging.getLogger(__name__)
MAX_SOURCE_CHARS = 1500


class WebEvidence(BaseModel):
    source: int = Field(description="n of the <source> the quote comes from")
    quote: str = Field(description="short span copied character-for-character from that source")


class WebSegmentOut(BaseModel):
    text: str = Field(description="one or two sentences of the answer")
    evidence: list[WebEvidence]


class WebAnswerOut(BaseModel):
    status: Literal["answered", "not_found"]
    segments: list[WebSegmentOut]


def verify(answer: WebAnswerOut, hits: list[SearchHit], fuzzy_min: float) -> list[WebSegment]:
    """Keep segments whose quotes are found in the named sources and whose numbers those sources contain."""
    kept: list[WebSegment] = []
    for seg in answer.segments:
        text = " ".join(seg.text.split())
        cited = sorted(
            {
                ev.source - 1
                for ev in seg.evidence
                if 1 <= ev.source <= len(hits) and match_quote(ev.quote, hits[ev.source - 1].content, fuzzy_min)
            }
        )
        if not text or not cited:
            continue
        if numbers_in(text) - numbers_in(" ".join(hits[i].content for i in cited)):
            continue
        kept.append(WebSegment(text=text, sources=cited))
    return kept


@traced("web_lookup")
async def web_lookup(
    llm: LLMProvider,
    engine: WebSearch,
    question: str,
    query: str,
    title: str,
    usage: dict[str, Any],
    model: str,
    thinking: str | None,
) -> WebResult:
    """Never raises: a failed search or answer becomes `unavailable` with a short note in our own words."""
    s = get_settings()
    started = time.perf_counter()
    usage["web_engine"] = engine.name
    try:
        hits = (await engine.search(query, s.web_search_max_results))[: s.web_search_max_results]
    except SearchUnavailable as e:
        return WebResult(status="unavailable", query=query, engine=engine.name, note=str(e))
    except Exception:
        log.exception("web_search_failed")
        return WebResult(status="unavailable", query=query, engine=engine.name, note="Web search failed.")
    finally:
        usage["web_search_ms"] = int((time.perf_counter() - started) * 1000)
    sources = [WebSource(title=h.title, uri=h.url, domain=h.domain) for h in hits]
    base = {"query": query, "sources": sources, "search_queries": [query], "engine": engine.name}
    if not hits:
        return WebResult(status="not_found", **base)

    clipped = [SearchHit(h.title, h.url, h.domain, h.content[:MAX_SOURCE_CHARS], h.score) for h in hits]
    levels, _ = s.thinking_for(model)
    web_usage: dict[str, Any] = {}
    buf = ""
    try:
        async for kind, delta in llm.stream_json(
            WEB_SYSTEM,
            build_web_prompt(question, title, [(h.title, h.domain, h.content) for h in clipped]),
            WebAnswerOut,
            web_usage,
            model=model,
            thinking=levels[0] if thinking and levels else None,  # cheapest level: a lookup, not a study
        ):
            if kind == "text":
                buf += delta
        answer = WebAnswerOut.model_validate_json(buf)
    except (ValidationError, ValueError):
        log.warning("web_answer_malformed")
        return WebResult(status="unavailable", note="The web answer couldn't be read.", **base)
    except Exception:
        log.exception("web_answer_failed")
        return WebResult(status="unavailable", note="Writing the web answer failed.", **base)
    finally:
        usage.update(
            web_model=model,
            web_input_tokens=web_usage.get("input_tokens", 0),
            web_output_tokens=web_usage.get("output_tokens", 0),
            web_ms=int((time.perf_counter() - started) * 1000),
        )
    segments = verify(answer, clipped, s.quote_fuzzy_min) if answer.status == "answered" else []
    trace_metadata(web_hits=len(hits), web_segments=len(answer.segments), web_kept=len(segments))
    return WebResult(status="answered" if segments else "not_found", segments=segments, **base)
