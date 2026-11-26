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
    suggestion: str = Field(
        default="",
        description="optional next step for the reader (a follow-up question or where to look next); no new facts",
    )
    web_query: str = Field(
        default="",
        description="a precise web search query when the blocks can't fully answer; empty when they do",
    )


class WebSource(BaseModel):
    title: str
    uri: str
    domain: str = ""


class WebSegment(BaseModel):
    text: str
    sources: list[int]  # indexes into WebResult.sources


class WebResult(BaseModel):
    """A web lookup. Only text the search grounding attributes to a source is kept, like verified segments."""

    status: Literal["answered", "not_found", "unavailable"]
    query: str
    segments: list[WebSegment] = []
    sources: list[WebSource] = []
    search_queries: list[str] = []
    entry_html: str | None = None  # Google's search-suggestion chip; must be shown with grounded results
    note: str | None = None  # why the lookup was unavailable (no content)


Delta = tuple[Literal["thought", "text"], str]


class WebSearchUnavailable(Exception):
    """The web lookup failed (quota, outage, model without search grounding). The document answer still stands."""


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
        """Answer from a web search. Raises WebSearchUnavailable when the lookup itself fails."""
        ...

    async def describe_models(self, model_ids: list[str]) -> list[dict[str, Any]]:
        """Metadata for the picker: input/output token limits, whether the model thinks. No generation."""
        ...

    async def check(self) -> dict[str, Any]:
        """Startup smoke check: configured models exist and structured output works."""
        ...
