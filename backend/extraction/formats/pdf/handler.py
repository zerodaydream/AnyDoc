from pathlib import Path

from backend.document_ir.models import ExtractResult
from backend.extraction.formats.pdf.extractor import extract_pdf


class PdfHandler:
    name: str = "pdf"
    extensions: tuple[str, ...] = (".pdf",)

    def sniff(self, head: bytes) -> bool:
        # The spec allows junk before the header; readers accept it within the first 1 KiB.
        return b"%PDF-" in head[:1024]

    def extract(self, path: Path, max_pages: int) -> ExtractResult:
        return extract_pdf(path, max_pages)
