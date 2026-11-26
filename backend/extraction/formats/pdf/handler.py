from pathlib import Path
from typing import Any

from backend.document_ir.models import ExtractLimits, ExtractResult
from backend.extraction.formats.pdf.extractor import extract_pdf


class PdfHandler:
    name: str = "pdf"
    label: str = "PDF"
    extensions: tuple[str, ...] = (".pdf",)
    media_type: str = "application/pdf"

    def sniff(self, head: bytes) -> bool:
        # The spec allows junk before the header; readers accept it within the first 1 KiB.
        return b"%PDF-" in head[:1024]

    def extract(self, path: Path, limits: ExtractLimits) -> ExtractResult:
        return extract_pdf(path, limits.max_pages)

    def extent(self, page_count: int | None, meta: dict[str, Any]) -> str | None:
        return None if page_count is None else f"{page_count:,} page{'' if page_count == 1 else 's'}"
