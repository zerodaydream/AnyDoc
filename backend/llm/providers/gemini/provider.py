"""Gemini via the official google-genai SDK. The only module that imports it."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from backend.core.errors import TransientError
from backend.llm.base import (
    Delta,
    UnsupportedOption,
    WebResult,
    WebSearchUnavailable,
    WebSegment,
    WebSource,
)
from backend.llm.prompts import WEB_SYSTEM, build_web_prompt

log = logging.getLogger(__name__)
_RETRYABLE = {408, 429, 500, 502, 503, 504}
# SDK-level retries (off unless set): exponential backoff with jitter on _RETRYABLE codes and network errors,
# per Google's guidance. Waits ~1s, 2s, 4s, 8s (+ up to 1s jitter each), capped at 60s; 5 attempts total.
_RETRY = types.HttpRetryOptions(
    attempts=5, initial_delay=1.0, max_delay=60.0, exp_base=2, jitter=1.0, http_status_codes=sorted(_RETRYABLE)
)


def _unavailable(mid: str) -> dict[str, Any]:
    return {
        "id": mid,
        "name": mid,
        "input_token_limit": None,
        "output_token_limit": None,
        "thinking": False,
        "available": False,
    }


class GeminiProvider:
    def __init__(self, api_key: str, model_id: str, fast_model_id: str, timeout_s: float) -> None:
        self.model_id = model_id
        self.fast_model_id = fast_model_id
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000), retry_options=_RETRY)
        )
        self._meta: dict[str, dict[str, Any]] = {}
        self._failed: dict[str, float] = {}

    async def stream_json(
        self,
        system: str,
        prompt: str,
        schema: type[BaseModel],
        usage: dict[str, Any],
        *,
        model: str | None = None,
        thinking: str | None = None,
    ) -> AsyncIterator[Delta]:
        model = model or self.model_id
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.0,
            thinking_config=(
                types.ThinkingConfig(thinking_level=types.ThinkingLevel(thinking.upper()), include_thoughts=True)
                if thinking
                else None
            ),
        )
        started = time.perf_counter()
        emitted = False
        try:
            # The SDK retries a failed stream open; a failure after output starts is not retried here (it would
            # duplicate text) and surfaces as TransientError so the engine can reset and restart.
            stream = await self._client.aio.models.generate_content_stream(model=model, contents=prompt, config=config)
            async for chunk in stream:
                if chunk.usage_metadata:
                    um = chunk.usage_metadata
                    usage.update(
                        model=model,
                        input_tokens=um.prompt_token_count or 0,
                        output_tokens=um.candidates_token_count or 0,
                        thinking_tokens=um.thoughts_token_count or 0,
                    )
                content = chunk.candidates[0].content if chunk.candidates else None
                for part in (content.parts or []) if content else []:
                    if not part.text:
                        continue
                    emitted = True
                    yield ("thought" if part.thought else "text", part.text)
            usage["latency_ms"] = int((time.perf_counter() - started) * 1000)
        except errors.APIError as e:
            if e.code == 400 and not emitted:
                # Usually an option this model doesn't support (thinking level, structured output).
                raise UnsupportedOption(f"{model} rejected this request: {str(e.message)[:200]}") from e
            if e.code in _RETRYABLE:
                raise TransientError(f"gemini {e.code}") from e
            raise

    async def web_answer(
        self,
        question: str,
        query: str,
        title: str,
        usage: dict[str, Any],
        *,
        model: str | None = None,
        thinking: str | None = None,
    ) -> WebResult:
        """One Google Search grounded call (no response schema: search + schema is unreliable, see D9)."""
        model = model or self.model_id
        config = types.GenerateContentConfig(
            system_instruction=WEB_SYSTEM,
            tools=[types.Tool(google_search=types.GoogleSearch())],
            thinking_config=(
                types.ThinkingConfig(thinking_level=types.ThinkingLevel(thinking.upper())) if thinking else None
            ),
        )
        started = time.perf_counter()
        try:  # SDK retries transient errors with backoff
            r = await self._client.aio.models.generate_content(
                model=model, contents=build_web_prompt(question, query, title), config=config
            )
        except errors.APIError as e:
            log.warning("gemini_web_failed", extra={"model": model, "code": e.code})
            if e.code == 429:
                raise WebSearchUnavailable("Web search quota is used up for this API key.") from e
            raise WebSearchUnavailable(f"Web search failed ({e.code}).") from e
        um = r.usage_metadata
        usage.update(
            web_model=model,
            web_input_tokens=(um.prompt_token_count or 0) if um else 0,
            web_output_tokens=(um.candidates_token_count or 0) if um else 0,
            web_ms=int((time.perf_counter() - started) * 1000),
        )
        gm = r.candidates[0].grounding_metadata if r.candidates else None
        return grounded_result(query, gm)

    async def describe_models(self, model_ids: list[str]) -> list[dict[str, Any]]:
        async def one(mid: str) -> dict[str, Any]:
            failed_at = self._failed.get(mid)
            if failed_at and time.monotonic() - failed_at < 300:  # don't re-hit a missing model on every picker load
                return _unavailable(mid)
            if mid not in self._meta:
                try:
                    m = await self._client.aio.models.get(model=mid)
                    self._meta[mid] = {
                        "id": mid,
                        "name": m.display_name or mid,
                        "input_token_limit": m.input_token_limit,
                        "output_token_limit": m.output_token_limit,
                        "thinking": bool(m.thinking),
                        "available": True,
                    }
                except errors.APIError as e:
                    log.warning("gemini_model_lookup_failed", extra={"model": mid, "code": e.code})
                    self._failed[mid] = time.monotonic()
                    return _unavailable(mid)
            return self._meta[mid]

        return list(await asyncio.gather(*(one(m) for m in model_ids)))

    async def check(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for mid in (self.model_id, self.fast_model_id):
            m = await self._client.aio.models.get(model=mid)
            out[mid] = {"input_token_limit": m.input_token_limit, "output_token_limit": m.output_token_limit}

        class Ping(BaseModel):
            ok: bool

        try:  # SDK retries "high demand" 503s with backoff
            r = await self._client.aio.models.generate_content(
                model=self.model_id,
                contents='Reply with {"ok": true}.',
                config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Ping),
            )
        except errors.APIError as e:
            if e.code not in _RETRYABLE:
                raise  # missing model, bad key, no access: fail loudly
            # Model exists (models.get passed) but is still overloaded after retries: start anyway.
            log.warning("gemini_check_model_busy", extra={"model": self.model_id, "code": e.code})
            out["structured_output"] = f"unverified: model busy ({e.code})"
            return out
        Ping.model_validate_json(r.text or "")
        out["structured_output"] = True
        return out


def grounded_result(query: str, gm: types.GroundingMetadata | None) -> WebResult:
    """Keep only text that grounding attributes to a web source; no attributed text means no answer."""
    if gm is None:
        return WebResult(status="not_found", query=query)
    chunks = [c.web for c in gm.grounding_chunks or [] if c.web and c.web.uri]
    sources = [WebSource(title=c.title or c.domain or "source", uri=c.uri or "", domain=c.domain or "") for c in chunks]
    segments: list[WebSegment] = []
    for sup in sorted(gm.grounding_supports or [], key=lambda x: (x.segment.start_index or 0) if x.segment else 0):
        text = (sup.segment.text or "").strip() if sup.segment else ""
        idx = sorted({i for i in sup.grounding_chunk_indices or [] if 0 <= i < len(sources)})
        if not text or not idx:
            continue
        if segments and segments[-1].text == text:
            segments[-1].sources = sorted({*segments[-1].sources, *idx})
        else:
            segments.append(WebSegment(text=text, sources=idx))
    entry = gm.search_entry_point.rendered_content if gm.search_entry_point else None
    return WebResult(
        status="answered" if segments else "not_found",
        query=query,
        segments=segments,
        sources=sources,
        search_queries=list(gm.web_search_queries or []),
        entry_html=entry or None,
    )
