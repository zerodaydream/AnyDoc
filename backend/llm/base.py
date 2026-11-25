from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    block_id: str = Field(description="id attribute of the document_block the quote comes from")
    quote: str = Field(description="short span copied character-for-character from that block")


class Segment(BaseModel):
    text: str = Field(description="one or two sentences of the answer")
    evidence: list[Evidence]


class AnswerOut(BaseModel):
    status: Literal["answered", "insufficient_evidence", "conflicting_evidence"]
    segments: list[Segment]


Delta = tuple[Literal["thought", "text"], str]


class UnsupportedOption(Exception):
    """The provider rejected a user-selected option (e.g. a thinking level the model doesn't support)."""


class LLMProvider(Protocol):
    model_id: str

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
        """Yield ("thought", text) reasoning summaries and ("text", json) answer deltas conforming to `schema`."""
        ...

    async def describe_models(self, model_ids: list[str]) -> list[dict[str, Any]]:
        """Metadata for the picker: input/output token limits, whether the model thinks. No generation."""
        ...

    async def check(self) -> dict[str, Any]:
        """Startup smoke check: configured models exist and structured output works."""
        ...
