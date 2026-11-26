from pathlib import Path
from typing import Any

from backend.document_ir.models import ExtractLimits, ExtractResult
from backend.extraction.formats.text.decode import looks_like_text
from backend.extraction.formats.text.extractor import extract_text


class TextHandler:
    """Plain text and Markdown share decoding, locations and viewer; only block detection differs."""

    def __init__(self, name: str, label: str, extensions: tuple[str, ...], media_type: str) -> None:
        self.name, self.label, self.extensions, self.media_type = name, label, extensions, media_type

    def sniff(self, head: bytes) -> bool:
        return looks_like_text(head[:4096])

    def extract(self, path: Path, limits: ExtractLimits) -> ExtractResult:
        return extract_text(path, limits, markdown=self.name == "markdown")

    def extent(self, page_count: int | None, meta: dict[str, Any]) -> str | None:
        n = meta.get("line_count")
        return None if n is None else f"{n:,} line{'' if n == 1 else 's'}"


TXT = TextHandler("text", "plain text", (".txt",), "text/plain")
MARKDOWN = TextHandler("markdown", "Markdown", (".md", ".markdown"), "text/markdown")
