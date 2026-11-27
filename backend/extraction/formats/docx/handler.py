from pathlib import Path
from typing import Any

from backend.document_ir.models import ExtractLimits, ExtractResult
from backend.extraction.formats.docx.extractor import CFB_MAGIC, extract_docx


class DocxHandler:
    name: str = "docx"
    label: str = "Word (.docx)"
    extensions: tuple[str, ...] = (".docx",)
    media_type: str = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def sniff(self, head: bytes) -> bool:
        # A .docx is a ZIP package. Password-protected ones are OLE files; let extract() say so clearly.
        return head.startswith(b"PK\x03\x04") or head.startswith(CFB_MAGIC)

    def extract(self, path: Path, limits: ExtractLimits) -> ExtractResult:
        return extract_docx(path, limits)

    def extent(self, page_count: int | None, meta: dict[str, Any]) -> str | None:
        n = meta.get("word_count")
        return None if n is None else f"{n:,} word{'' if n == 1 else 's'}"
