"""Format registry. Adding a format = one new handler module + one entry in HANDLERS (and its kind below).

Tabular formats may also register a QueryTool: the answer engine then lets the model plan exact computations over
the whole file before answering (ADR-0006). The engine knows only this protocol, never the format.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from backend.core.errors import InvalidFile
from backend.document_ir.models import ExtractLimits, ExtractResult, IRBlock
from backend.extraction.formats.csv.handler import CsvHandler
from backend.extraction.formats.csv.locate import label_csv, locate_csv
from backend.extraction.formats.csv.query import CSV_QUERIES
from backend.extraction.formats.docx.handler import DocxHandler
from backend.extraction.formats.docx.locate import label_docx, locate_docx
from backend.extraction.formats.pdf.handler import PdfHandler
from backend.extraction.formats.pdf.locate import label_pdf, locate_pdf
from backend.extraction.formats.text.handler import MARKDOWN, TXT
from backend.extraction.formats.text.locate import label_text, locate_text


class FormatHandler(Protocol):
    name: str
    label: str  # shown to people: "PDF", "Markdown"
    extensions: tuple[str, ...]
    media_type: str  # served with the original file

    def sniff(self, head: bytes) -> bool:
        """Magic-byte check on the first bytes of the file."""
        ...

    def extract(self, path: Path, limits: ExtractLimits) -> ExtractResult:
        """Validate + extract. Runs inside the sandbox; raises InvalidFile for bad input."""
        ...

    def extent(self, page_count: int | None, meta: dict[str, Any]) -> str | None:
        """How big the document is, in its own unit: "15 pages", "1,240 lines"."""
        ...


class QueryTool(Protocol):
    """Exact computations over a structured file (brief §6.7). The model fills `plan_schema`; `run` executes it in
    the sandbox and returns evidence blocks whose locations are the cells it read."""

    plan_schema: type[BaseModel]
    plan_system: str

    def plan_prompt(self, meta: dict[str, Any], question: str, history: list[tuple[str, str]]) -> str:
        """Schema of the document (from extraction metadata, no file read) + the question, for the planning call."""
        ...

    def run(self, path: Path, plan: dict[str, Any], limits: ExtractLimits) -> list[IRBlock]:
        """Execute a validated plan over the original file. Runs inside the sandbox; picklable in and out."""
        ...


HANDLERS: tuple[FormatHandler, ...] = (PdfHandler(), TXT, MARKDOWN, DocxHandler(), CsvHandler())
_QUERY_TOOLS: dict[str, QueryTool] = {"csv": CSV_QUERIES}


def supported() -> str:
    return ", ".join(h.label for h in HANDLERS[:-1]) + f" or {HANDLERS[-1].label}"


def detect(filename: str, head: bytes) -> FormatHandler:
    """Extension and magic bytes must agree. The parse test happens in extract()."""
    ext = Path(filename).suffix.lower()
    for h in HANDLERS:
        if ext in h.extensions:
            if not h.sniff(head):
                raise InvalidFile("type_mismatch", f"This file is named {ext}, but its contents aren't {h.label}.")
            return h
    raise InvalidFile("unsupported_format", f"{ext or 'This file type'} is not supported yet. Upload {supported()}.")


def handler_for(name: str) -> FormatHandler:
    return next(h for h in HANDLERS if h.name == name)


def query_tool(name: str | None) -> QueryTool | None:
    return _QUERY_TOOLS.get(name or "")


# Keyed by SourceLocation.kind (several formats may share one kind, as TXT and Markdown do).
Locator = Callable[[str, int | None, dict[str, Any], int, int], BaseModel]
_LOCATORS: dict[str, Locator] = {"pdf": locate_pdf, "text": locate_text, "docx": locate_docx, "csv": locate_csv}
_LABELS: dict[str, Callable[[dict[str, Any]], str]] = {
    "pdf": label_pdf,
    "text": label_text,
    "docx": label_docx,
    "csv": label_csv,
}


def locate(
    kind: str, content: str, page: int | None, format_metadata: dict[str, Any], start: int, end: int
) -> dict[str, Any]:
    """Char span inside a block -> precise source location, computed from the IR only."""
    return _LOCATORS[kind](content, page, format_metadata, start, end).model_dump()


def describe(location: dict[str, Any]) -> str:
    """Where a location is, in words a reader uses: "page 7", "lines 12–14"."""
    return _LABELS[location["kind"]](location)
