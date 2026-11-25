"""PDF -> IR blocks with word boxes, using PDFium char-level text (ADR-0001).

Runs inside the parsing sandbox: pure function, no DB, no network.
"""

import hashlib
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from backend.core.errors import InvalidFile
from backend.document_ir.models import ExtractResult, IRBlock, PdfLocation, PdfRegion

_LINE_BREAKS = {"\r", "\n"}
_SOFT_HYPHENS = {0x02, 0xAD, 0xFFFE}
_VERSION = version("pypdfium2")


@dataclass(slots=True)
class Word:
    text: str
    box: tuple[float, float, float, float]  # l, b, r, t (user space)
    size: float
    bold: bool


@dataclass(slots=True)
class Line:
    words: list[Word] = field(default_factory=list)

    @property
    def box(self) -> tuple[float, float, float, float]:
        return (
            min(w.box[0] for w in self.words),
            min(w.box[1] for w in self.words),
            max(w.box[2] for w in self.words),
            max(w.box[3] for w in self.words),
        )

    @property
    def size(self) -> float:
        return statistics.median(w.size for w in self.words)

    @property
    def height(self) -> float:
        b = self.box
        return max(b[3] - b[1], 1.0)


def open_pdf(path: Path) -> pdfium.PdfDocument:
    try:
        return pdfium.PdfDocument(path)
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise InvalidFile(
                "encrypted_pdf", "This PDF is password-protected. Remove the password and upload it again."
            ) from e
        raise InvalidFile(
            "malformed_pdf", "This PDF couldn't be opened: the file is damaged. Try exporting it again."
        ) from e


def _page_lines(page: pdfium.PdfPage) -> list[Line]:
    tp = page.get_textpage()
    try:
        n = tp.count_chars()
        lines: list[Line] = []
        line = Line()
        chars: list[str] = []
        box: list[float] | None = None
        sizes: list[float] = []
        bold = False

        def end_word() -> None:
            nonlocal chars, box, sizes, bold
            if chars and box is not None:
                line.words.append(
                    Word("".join(chars), (box[0], box[1], box[2], box[3]), statistics.median(sizes), bold)
                )
            chars, box, sizes = [], None, []

        def end_line() -> None:
            nonlocal line
            end_word()
            if line.words:
                lines.append(line)
            line = Line()

        for i in range(n):
            cp = raw.FPDFText_GetUnicode(tp.raw, i)
            ch = chr(cp) if cp else " "
            if ch in _LINE_BREAKS:
                end_line()
                continue
            if ch.isspace():
                end_word()
                continue
            l, b, r, t = tp.get_charbox(i)
            if cp in _SOFT_HYPHENS:  # line-end hyphen PDFium marks specially; keep it visible, end the word
                if chars and box is not None:
                    chars.append("-")
                    box[2] = max(box[2], r)
                end_word()
                continue
            # A char far below/above the current line starts a new line even without a generated break.
            if line.words and chars == [] and abs(b - line.words[-1].box[1]) > 0.6 * line.height:
                end_line()
            box = [l, b, r, t] if box is None else [min(box[0], l), min(box[1], b), max(box[2], r), max(box[3], t)]
            if not chars:
                bold = raw.FPDFText_GetFontWeight(tp.raw, i) >= 600
            sizes.append(raw.FPDFText_GetFontSize(tp.raw, i) or (t - b))
            chars.append(ch)
        end_line()
        return lines
    finally:
        tp.close()


def _same_block(prev: Line, cur: Line) -> bool:
    pb, cb = prev.box, cur.box
    gap = pb[1] - cb[3]  # positive when cur is below prev
    if gap < -0.5 * prev.height:  # moved up: new column or out-of-order text
        return False
    if gap > 0.9 * max(prev.height, cur.height):
        return False
    return abs(prev.size - cur.size) <= 0.15 * max(prev.size, cur.size)


def _rnd(v: float) -> float:
    return round(v, 2)


def _build_block(lines: list[Line], page_no: int, idx: int, ordinal: int, body_size: float) -> IRBlock:
    parts: list[str] = []
    words_meta: list[list[float]] = []
    rects: list[list[float]] = []
    pos = 0
    for ln in lines:
        for w in ln.words:
            if parts:
                parts.append(" ")
                pos += 1
            words_meta.append([pos, pos + len(w.text), *(_rnd(v) for v in w.box)])
            parts.append(w.text)
            pos += len(w.text)
        rects.append([_rnd(v) for v in ln.box])
    content = "".join(parts)
    size = statistics.median(ln.size for ln in lines)
    # Rotated text (e.g. arXiv sidebars) yields lines taller than wide: never a heading.
    horizontal = all((ln.box[2] - ln.box[0]) >= (ln.box[3] - ln.box[1]) for ln in lines)
    short = len(words_meta) <= 20 and any(c.isalpha() for c in content)
    bold_line = len(lines) == 1 and len(words_meta) <= 12 and all(w.bold for w in lines[0].words)
    is_heading = horizontal and short and (size >= 1.2 * body_size or bold_line)
    digest = hashlib.sha1(content.encode(), usedforsecurity=False).hexdigest()[:8]
    return IRBlock(
        block_id=f"pdf:{page_no}:{idx}:{digest}",
        ordinal=ordinal,
        type="heading" if is_heading else "paragraph",
        content=content,
        page=page_no,
        source_location=PdfLocation(regions=[PdfRegion(page=page_no, rects=rects)]),
        format_metadata={"words": words_meta, "font_size": _rnd(size)},
    )


def extract_pdf(path: Path, max_pages: int, on_page: Callable[[int, int], None] | None = None) -> ExtractResult:
    doc = open_pdf(path)
    try:
        page_count = len(doc)
        if page_count > max_pages:
            raise InvalidFile("too_many_pages", f"This PDF has {page_count} pages; the limit is {max_pages}.")
        pages: list[list[Line]] = []
        for i in range(page_count):
            page = doc[i]
            try:
                pages.append(_page_lines(page))
            finally:
                page.close()
            if on_page:
                on_page(i + 1, page_count)
        title = (doc.get_metadata_dict().get("Title") or "").strip()
    finally:
        doc.close()

    all_sizes = [ln.size for p in pages for ln in p]
    if not all_sizes:
        raise InvalidFile(
            "no_text_layer",
            "This PDF has no selectable text (it may be scanned). Scanned documents are supported in a later version.",
        )
    body_size = statistics.median(all_sizes)

    blocks: list[IRBlock] = []
    section: list[str] = []
    for page_no, lines in enumerate(pages, start=1):
        groups: list[list[Line]] = []
        for ln in lines:
            if groups and _same_block(groups[-1][-1], ln):
                groups[-1].append(ln)
            else:
                groups.append([ln])
        for idx, g in enumerate(groups):
            b = _build_block(g, page_no, idx, len(blocks), body_size)
            if b.type == "heading":
                section = [b.content[:200]]
            b.section_path = list(section)
            blocks.append(b)

    empty_pages = [i for i, p in enumerate(pages, start=1) if not p]
    return ExtractResult(
        page_count=page_count,
        blocks=blocks,
        metadata={"title": title, "pages_without_text": empty_pages, "extractor": f"pypdfium2-{_VERSION}"},
    )
