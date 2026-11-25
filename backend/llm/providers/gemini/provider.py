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

log = logging.getLogger(__name__)
_RETRYABLE = {408, 429, 500, 502, 503, 504}


class GeminiProvider:
    def __init__(self, api_key: str, model_id: str, fast_model_id: str, timeout_s: float) -> None:
        self.model_id = model_id
        self.fast_model_id = fast_model_id
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))

    async def stream_json(
        self, system: str, prompt: str, schema: type[BaseModel], usage: dict[str, Any]
    ) -> AsyncIterator[str]:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.0,
        )
        started = time.perf_counter()
        for attempt in range(3):
            emitted = False
            try:
                stream = await self._client.aio.models.generate_content_stream(
                    model=self.model_id, contents=prompt, config=config
                )
                async for chunk in stream:
                    if chunk.usage_metadata:
                        um = chunk.usage_metadata
                        usage.update(
                            model=self.model_id,
                            input_tokens=um.prompt_token_count or 0,
                            output_tokens=um.candidates_token_count or 0,
                            thinking_tokens=um.thoughts_token_count or 0,
                        )
                    if chunk.text:
                        emitted = True
                        yield chunk.text
                usage["latency_ms"] = int((time.perf_counter() - started) * 1000)
                return
            except errors.APIError as e:
                # Retry only before any output reached the caller; mid-stream retries would duplicate text.
                if emitted or e.code not in _RETRYABLE or attempt == 2:
                    if e.code in _RETRYABLE:
                        raise TransientError(f"gemini {e.code}") from e
                    raise
                log.warning("gemini_retry", extra={"code": e.code, "attempt": attempt + 1})
                await asyncio.sleep(2**attempt)

    async def check(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for mid in (self.model_id, self.fast_model_id):
            m = await self._client.aio.models.get(model=mid)
            out[mid] = {"input_token_limit": m.input_token_limit, "output_token_limit": m.output_token_limit}

        class Ping(BaseModel):
            ok: bool

        for attempt in range(4):  # model "high demand" 503s are common and transient
            try:
                r = await self._client.aio.models.generate_content(
                    model=self.model_id,
                    contents='Reply with {"ok": true}.',
                    config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Ping),
                )
                break
            except errors.APIError as e:
                if e.code not in _RETRYABLE:
                    raise  # missing model, bad key, no access: fail loudly
                if attempt == 3:
                    # Model exists (models.get passed) but is overloaded: start, and let requests retry.
                    log.warning("gemini_check_model_busy", extra={"model": self.model_id, "code": e.code})
                    out["structured_output"] = f"unverified: model busy ({e.code})"
                    return out
                await asyncio.sleep(2 * 2**attempt)
        Ping.model_validate_json(r.text or "")
        out["structured_output"] = True
        return out
