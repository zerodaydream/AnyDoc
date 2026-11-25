"""Map a verified char span of a PDF block to highlight rects, from the block's own word boxes."""

from typing import Any

from backend.document_ir.models import PdfLocation, PdfRegion


def locate_pdf(page: int | None, format_metadata: dict[str, Any], start: int, end: int) -> PdfLocation:
    assert page is not None, "PDF blocks always carry a page"
    rects: list[list[float]] = []
    for w_start, w_end, l, b, r, t in format_metadata["words"]:
        if w_end <= start or w_start >= end:
            continue
        last = rects[-1] if rects else None
        # Merge with the previous rect when on the same line (vertical overlap > 50%).
        if last and min(last[3], t) - max(last[1], b) > 0.5 * min(last[3] - last[1], t - b) and l >= last[0]:
            last[0], last[1], last[2], last[3] = (
                min(last[0], l),
                min(last[1], b),
                max(last[2], r),
                max(last[3], t),
            )
        else:
            rects.append([l, b, r, t])
    return PdfLocation(regions=[PdfRegion(page=page, rects=rects)], char_start=start, char_end=end)
