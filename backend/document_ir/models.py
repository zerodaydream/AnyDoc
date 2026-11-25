"""Format-independent Document IR. Locations are produced by extractors, never by the LLM."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

# PDF user-space rect: [x0, y0, x1, y1], origin bottom-left, unrotated (what pdf.js
# viewport.convertToViewportRectangle expects).
Rect = list[float]


class PdfRegion(BaseModel):
    page: int  # 1-based
    rects: list[Rect]


class PdfLocation(BaseModel):
    kind: Literal["pdf"] = "pdf"
    regions: list[PdfRegion]
    char_start: int | None = None  # offsets into the block content
    char_end: int | None = None


# New formats add a variant here; consumers switch on `kind`.
SourceLocation = Annotated[PdfLocation, Field(discriminator="kind")]

BlockType = Literal["heading", "paragraph"]


class IRBlock(BaseModel):
    block_id: str
    ordinal: int
    type: BlockType
    content: str
    page: int | None
    source_location: SourceLocation
    format_metadata: dict[str, Any] = {}
    confidence: float | None = None  # None = native text layer
    section_path: list[str] = []

    @property
    def token_estimate(self) -> int:
        # shortcut: chars/4 heuristic, exact counts come from the provider at answer time
        return max(1, len(self.content) // 4)


class ExtractResult(BaseModel):
    page_count: int
    blocks: list[IRBlock]
    metadata: dict[str, Any] = {}
