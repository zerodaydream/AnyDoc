"""Map a verified char span of a DOCX block to paragraphs + offsets, from the IR only.

A block's `format_metadata["segments"]` lists where each piece of its content came from:
[content_start, content_end, para, para_start, ref] (ref = paragraph number, or row number inside `table`).
A table quote may cross cells, so one citation can cover several paragraphs (one region each).
"""

from typing import Any

from backend.document_ir.models import DocxLocation, DocxRegion


def locate_docx(content: str, page: int | None, format_metadata: dict[str, Any], start: int, end: int) -> DocxLocation:
    segments: list[list[int]] = format_metadata["segments"]
    hits = [s for s in segments if max(s[0], start) < min(s[1], end)]
    if not hits:  # the span sits on a separator between cells: point at the nearest piece
        hits = [next((s for s in segments if s[1] >= end), segments[-1])]
        start, end = hits[0][0], hits[0][1]
    regions = [
        DocxRegion(para=para, char_start=ps + max(cs, start) - cs, char_end=ps + min(ce, end) - cs)
        for cs, ce, para, ps, _ in hits
    ]
    first, last = min(s[4] for s in hits), max(s[4] for s in hits)
    table = format_metadata.get("table")
    if table:
        return DocxLocation(regions=regions, table=table, row_start=first, row_end=last)
    return DocxLocation(regions=regions, paragraph_start=first, paragraph_end=last)


def label_docx(location: dict[str, Any]) -> str:
    if location.get("table"):
        a, b = location["row_start"], location["row_end"]
        return f"table {location['table']}, " + (f"row {a:,}" if a == b else f"rows {a:,}–{b:,}")
    a, b = location.get("paragraph_start"), location.get("paragraph_end")
    if a is None or b is None:
        return "document"
    return f"paragraph {a:,}" if a == b else f"paragraphs {a:,}–{b:,}"
