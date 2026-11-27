"""Groq via the official groq SDK. The only module that imports it.

Each answer is one JSON-mode call, not streamed: in JSON mode Groq sends the whole answer as one chunk even when
streaming (seen live), and its speed keeps the wait short. JSON mode checks syntax only, so the schema goes in the
system prompt; the engine validates the answer strictly, as for every provider.

Thinking: a chosen level is sent as `reasoning_effort`, and the reasoning Groq returns in JSON mode
(`message.reasoning`) is shown as the thought summary. With thinking off nothing is sent: direct models answer
directly, and models that always reason (gpt-oss) keep their reasoning hidden.
"""

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, cast

import groq
from pydantic import BaseModel

from backend.core.errors import TransientError
from backend.llm.base import Delta, UnsupportedOption

log = logging.getLogger(__name__)
_RETRYABLE = {408, 429, 498, 500, 502, 503, 504}  # 498: Groq flex tier at capacity


def _json_instruction(schema: type[BaseModel]) -> str:
    return "\n\nReply with only one JSON object that matches this JSON schema. Include every property:\n" + json.dumps(
        schema.model_json_schema(), separators=(",", ":")
    )


def _entry(mid: str, extra: dict[str, Any], *, available: bool) -> dict[str, Any]:
    return {
        "id": mid,
        "name": mid,
        "input_token_limit": extra.get("context_window"),
        "output_token_limit": extra.get("max_completion_tokens"),
        "thinking": True,  # the API doesn't say; GROQ_MODELS_ENABLED levels decide what the picker offers
        "available": available,
    }


class GroqProvider:
    def __init__(self, api_key: str, model_id: str, fast_model_id: str, timeout_s: float) -> None:
        self.model_id = model_id
        self.fast_model_id = fast_model_id
        # The SDK retries connection errors, 408, 409, 429 and 5xx with exponential backoff and jitter, and honours
        # Retry-After. 4 retries = 5 attempts, as for Gemini.
        self._client = groq.AsyncGroq(api_key=api_key, timeout=timeout_s, max_retries=4)
        self._meta: dict[str, dict[str, Any]] = {}

    async def _json(self, model: str, system: str, prompt: str, thinking: str | None = None) -> Any:
        try:
            return await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
                reasoning_effort=cast(Any, thinking) if thinking else groq.omit,
            )
        except groq.APIStatusError as e:
            if e.status_code == 413:
                raise UnsupportedOption(f"{model} rejected this request as too large for your Groq plan.") from e
            if e.status_code == 400:  # usually an option this model doesn't support (thinking level)
                raise UnsupportedOption(f"{model} rejected this request: {str(e.message)[:200]}") from e
            if e.status_code in _RETRYABLE:
                raise TransientError(f"groq {e.status_code}") from e
            raise
        except groq.APIConnectionError as e:  # includes timeouts
            raise TransientError("groq connection failed") from e

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
        started = time.perf_counter()
        r = await self._json(model, system + _json_instruction(schema), prompt, thinking)
        if r.usage:
            details = r.usage.completion_tokens_details
            usage.update(
                model=model,
                input_tokens=r.usage.prompt_tokens,
                output_tokens=r.usage.completion_tokens,
                thinking_tokens=(details.reasoning_tokens or 0) if details else 0,
            )
        usage["latency_ms"] = int((time.perf_counter() - started) * 1000)
        message = r.choices[0].message
        if thinking and message.reasoning:
            yield ("thought", message.reasoning)
        yield ("text", message.content or "")

    async def describe_models(self, model_ids: list[str]) -> list[dict[str, Any]]:
        if any(m not in self._meta for m in model_ids):
            try:
                catalog = await self._catalog()
            except groq.APIError as e:  # nothing cached: the next request looks again
                log.warning("groq_model_lookup_failed", extra={"error": type(e).__name__})
                catalog = {}
            self._meta.update({m: _entry(m, catalog[m], available=True) for m in model_ids if m in catalog})
        return [self._meta.get(m) or _entry(m, {}, available=False) for m in model_ids]

    async def _catalog(self) -> dict[str, dict[str, Any]]:
        """Models this key can use, with limits (not in the SDK's typed fields). One list call: retrieving a single
        model URL-encodes the "/" in ids like qwen/qwen3.8-27b, and Groq answers 404 (seen live, groq 1.7.0)."""
        return {m.id: m.model_extra or {} for m in (await self._client.models.list()).data}

    async def check(self) -> dict[str, Any]:
        # Raises on a bad key or a missing model: fail loudly at startup.
        catalog = await self._catalog()
        out: dict[str, Any] = {}
        for mid in (self.model_id, self.fast_model_id):
            if mid not in catalog:
                raise RuntimeError(f"Groq model {mid!r} does not exist or this key has no access to it.")
            out[mid] = _entry(mid, catalog[mid], available=True)

        class Ping(BaseModel):
            ok: bool

        r = await self._json(self.model_id, "Answer in JSON." + _json_instruction(Ping), 'Reply with {"ok": true}.')
        Ping.model_validate_json(r.choices[0].message.content or "")
        out["structured_output"] = True
        return out
