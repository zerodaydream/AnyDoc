"""Map a verified char span of a text block to file offsets and line numbers, from the IR only."""

from typing import Any

from backend.document_ir.models import TextLocation, TextRegion


def locate_text(content: str, page: int | None, format_metadata: dict[str, Any], start: int, end: int) -> TextLocation:
    base, line = int(format_metadata["start"]), int(format_metadata["line"])
    return TextLocation(
        regions=[
            TextRegion(
                char_start=base + start,
                char_end=base + end,
                line_start=line + content.count("\n", 0, start),
                line_end=line + content.count("\n", 0, max(start, end - 1)),
            )
        ]
    )


def label_text(location: dict[str, Any]) -> str:
    regions = location["regions"]
    first, last = min(r["line_start"] for r in regions), max(r["line_end"] for r in regions)
    return f"line {first:,}" if first == last else f"lines {first:,}–{last:,}"
