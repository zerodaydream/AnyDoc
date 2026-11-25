"""Format registry. Adding a format = one new handler module + one entry here."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from backend.core.errors import InvalidFile
from backend.document_ir.models import ExtractResult
from backend.extraction.formats.pdf.handler import PdfHandler
from backend.extraction.formats.pdf.locate import locate_pdf


class FormatHandler(Protocol):
    name: str
    extensions: tuple[str, ...]

    def sniff(self, head: bytes) -> bool:
        """Magic-byte check on the first bytes of the file."""
        ...

    def extract(self, path: Path, max_pages: int) -> ExtractResult:
        """Validate + extract. Runs inside the sandbox; raises InvalidFile for bad input."""
        ...


HANDLERS: tuple[FormatHandler, ...] = (PdfHandler(),)


def detect(filename: str, head: bytes) -> FormatHandler:
    """Extension and magic bytes must agree. The parse test happens in extract()."""
    ext = Path(filename).suffix.lower()
    for h in HANDLERS:
        if ext in h.extensions:
            if not h.sniff(head):
                raise InvalidFile(
                    "type_mismatch", f"This file is named {ext} but its contents are not {h.name.upper()}."
                )
            return h
    raise InvalidFile("unsupported_format", f"{ext or 'This file type'} is not supported yet. Upload a PDF.")


def handler_for(name: str) -> FormatHandler:
    return next(h for h in HANDLERS if h.name == name)


Locator = Callable[[int | None, dict[str, Any], int, int], BaseModel]
_LOCATORS: dict[str, Locator] = {"pdf": locate_pdf}  # keyed by SourceLocation.kind


def locate(kind: str, page: int | None, format_metadata: dict[str, Any], start: int, end: int) -> dict[str, Any]:
    """Char span inside a block -> precise source location, computed from the IR only."""
    return _LOCATORS[kind](page, format_metadata, start, end).model_dump()
