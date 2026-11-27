"""Sends each call to the provider that owns the requested model (the picker's Gemini and Groq tabs)."""

from collections.abc import AsyncIterator, Callable
from typing import Any

from pydantic import BaseModel

from backend.llm.base import Delta, LLMProvider, WebResult


class RoutedProvider:
    def __init__(
        self, providers: dict[str, LLMProvider], provider_for: Callable[[str], str], default_model: str
    ) -> None:
        self.model_id = default_model
        self._providers = providers
        self._provider_for = provider_for

    def _pick(self, model: str) -> LLMProvider:
        return self._providers[self._provider_for(model)]

    def stream_json(
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
        return self._pick(model).stream_json(system, prompt, schema, usage, model=model, thinking=thinking)

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
        model = model or self.model_id
        return await self._pick(model).web_answer(question, query, title, usage, model=model, thinking=thinking)

    async def describe_models(self, model_ids: list[str]) -> list[dict[str, Any]]:
        meta: dict[str, dict[str, Any]] = {}
        for name, provider in self._providers.items():
            if ids := [m for m in model_ids if self._provider_for(m) == name]:
                meta.update({m["id"]: m for m in await provider.describe_models(ids)})
        return [meta[m] for m in model_ids if m in meta]

    async def check(self) -> dict[str, Any]:
        return {name: await provider.check() for name, provider in self._providers.items()}
