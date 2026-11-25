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


class LLMProvider(Protocol):
    model_id: str

    def stream_json(
        self, system: str, prompt: str, schema: type[BaseModel], usage: dict[str, Any]
    ) -> AsyncIterator[str]:
        """Yield raw JSON text deltas conforming to `schema`. Fills `usage` when done."""
        ...

    async def check(self) -> dict[str, Any]:
        """Startup smoke check: configured models exist and structured output works."""
        ...
