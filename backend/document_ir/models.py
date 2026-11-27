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


class TextRegion(BaseModel):
    # Code-point offsets into the decoded, newline-normalised file text (see formats/text/decode.py).
    char_start: int
    char_end: int
    line_start: int  # 1-based, inclusive
    line_end: int


class TextLocation(BaseModel):
    kind: Literal["text"] = "text"
    regions: list[TextRegion]


class DocxRegion(BaseModel):
    # `para`: 0-based index of the w:p among all paragraphs the viewer renders, in document order (body,
    # table cells, content controls; see formats/docx/extractor.py). Offsets are code points into its text.
    para: int
    char_start: int
    char_end: int


class DocxLocation(BaseModel):
    kind: Literal["docx"] = "docx"
    regions: list[DocxRegion]
    # For people: 1-based numbers of the non-empty body paragraphs, or the table and its rows.
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    table: int | None = None
    row_start: int | None = None
    row_end: int | None = None


class CsvRegion(BaseModel):
    # A rectangle of cells. Rows are 1-based record numbers in the file (the header is row 1 when there is one;
    # blank lines count), columns 0-based and inclusive. See formats/csv/table.py.
    row_start: int
    row_end: int
    col_start: int
    col_end: int


class CsvLocation(BaseModel):
    kind: Literal["csv"] = "csv"
    regions: list[CsvRegion]
    rows: int  # distinct rows covered (a computed result can cover rows far apart)
    columns: list[str] = []  # names of the columns covered; empty = whole rows
    truncated: bool = False  # more cells were read than the regions list (capped for size)


# New formats add a variant here; consumers switch on `kind`.
SourceLocation = Annotated[PdfLocation | TextLocation | DocxLocation | CsvLocation, Field(discriminator="kind")]

BlockType = Literal["heading", "paragraph", "list_item", "quote", "code", "table"]


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


class ExtractLimits(BaseModel):
    max_pages: int
    max_chars: int


class ExtractResult(BaseModel):
    page_count: int | None  # None for formats without pages
    blocks: list[IRBlock]
    metadata: dict[str, Any] = {}
