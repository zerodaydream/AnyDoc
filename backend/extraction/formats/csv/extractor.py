"""CSV -> IR blocks: runs of rows, each block led by the column names so it reads on its own.

    Columns: Region | Amount | Date
    Row 2: West | 120.50 | 2026-01-03

Every cell's span is recorded (`[start, end, row, col]`), so a quote maps to exact cells. The "Row 2:" prefix is
ours, not the file's: it lets answers name rows, and it maps to the whole row. Cell text is shown with inner
newlines and runs of spaces collapsed (the quote matcher normalises whitespace anyway); cells longer than
MAX_CELL_CHARS are cut in the block (documented limitation). Totals, counts and other computations don't come from
these blocks but from table queries over the whole file (query.py).

Title lines above the header (the preamble, see table.py) become one block of their own, filled cells only:

    Row 1: EU Region eCTD Validation Criteria Version 7.1 February 2018
"""

import hashlib
from pathlib import Path
from typing import Any

from backend.core.errors import InvalidFile
from backend.document_ir.models import ExtractLimits, ExtractResult, IRBlock
from backend.extraction.formats.csv.locate import locate_csv
from backend.extraction.formats.csv.table import ISO_DATE, Table, mostly_numbers, read_table, to_number

MAX_BLOCK_CHARS = 1500
MAX_BLOCK_ROWS = 40
MAX_CELL_CHARS = 1000
EXAMPLES = 3


def cell_text(value: str) -> str:
    t = " ".join(value.split())
    return t if len(t) <= MAX_CELL_CHARS else t[:MAX_CELL_CHARS] + "…"


def add_line(content: str, segments: list[list[int]], prefix: str, cells: list[tuple[int, int, str]]) -> str:
    """Append `prefix` + cells joined by " | " as a new line; record each cell's span. cells: (row, col, text)."""
    line = prefix
    base = len(content) + (1 if content else 0)
    for k, (row, col, text) in enumerate(cells):
        if k:
            line += " | "
        if text:
            segments.append([base + len(line), base + len(line) + len(text), row, col])
        line += text
    return content + ("\n" if content else "") + line


def header_line(table: Table, segments: list[list[int]], content: str = "") -> str:
    """ "Columns: ..." with the header cells mapped to the header row (synthetic names like "Column C" map to
    nothing)."""
    real = {k for k, v in enumerate(table.head()) if v.strip()}
    row = table.header_row or 0
    n = len(segments)
    content = add_line(content, segments, "Columns: ", [(row, k, cell_text(c)) for k, c in enumerate(table.columns)])
    segments[n:] = [s for s in segments[n:] if s[3] in real]
    return content


def row_cells(row_no: int, cells: list[str]) -> list[tuple[int, int, str]]:
    return [(row_no, k, cell_text(v)) for k, v in enumerate(cells)]


def profile(table: Table) -> list[dict[str, Any]]:
    """Per column: type, how many cells are filled, distinct values, examples (+ min/max for numbers, and how many
    filled cells aren't numbers, with a few of them, so the planner knows a sum will leave them out)."""
    data = table.data_rows()
    out: list[dict[str, Any]] = []
    for k, name in enumerate(table.columns):
        values = [v for _, r in data if k < len(r) and (v := r[k].strip())]
        nums = [n for v in values if (n := to_number(v)) is not None]
        col: dict[str, Any] = {"name": name, "filled": len(values), "distinct": len(set(values))}
        if mostly_numbers(values):
            col.update(type="number", min=min(nums), max=max(nums))
            others = [v for v in values if to_number(v) is None]
            if others:
                col["not_numbers"] = len(others)
                col["not_number_examples"] = [cell_text(v)[:40] for v in dict.fromkeys(others)][:EXAMPLES]
        elif values and sum(1 for v in values if ISO_DATE.match(v)) >= 0.9 * len(values):
            col.update(type="date", min=min(values), max=max(values))
        else:
            col["type"] = "text"
        col["examples"] = [cell_text(v)[:40] for v in dict.fromkeys(values)][:EXAMPLES]
        out.append(col)
    return out


def extract_csv(path: Path, limits: ExtractLimits) -> ExtractResult:
    table = read_table(path, limits.max_chars)
    names = table.columns
    blocks: list[IRBlock] = []
    content, first, count = "", 0, 0
    segments: list[list[int]] = []

    def flush() -> None:
        nonlocal content, segments, count
        if count:
            m: dict[str, Any] = {"segments": segments, "columns": names}
            digest = hashlib.sha1(content.encode(), usedforsecurity=False).hexdigest()[:8]
            blocks.append(
                IRBlock(
                    block_id=f"csv:{first}:{len(blocks)}:{digest}",
                    ordinal=len(blocks),
                    type="table",
                    content=content,
                    page=None,
                    source_location=locate_csv(content, None, m, 0, len(content)),
                    format_metadata=m,
                )
            )
        content, segments, count = "", [], 0

    for row_no, cells in table.preamble_rows():
        if not count:
            first = row_no
        filled = [(row_no, k, cell_text(v)) for k, v in enumerate(cells) if v.strip()]
        if filled:
            content = add_line(content, segments, f"Row {row_no}: ", filled)
            count += 1
    flush()

    for row_no, cells in table.data_rows():
        if not any(c.strip() for c in cells):  # ",,," carries nothing to quote
            continue
        line_cells = row_cells(row_no, cells)
        size = sum(len(t) + 3 for _, _, t in line_cells) + 12
        if count and (count >= MAX_BLOCK_ROWS or len(content) + size > MAX_BLOCK_CHARS):
            flush()
        if not count:
            first = row_no
            content = header_line(table, segments)
        content = add_line(content, segments, f"Row {row_no}: ", line_cells)
        count += 1
    flush()
    if not blocks:
        raise InvalidFile("no_rows", "This CSV file has no values in it.")

    data = table.data_rows()
    return ExtractResult(
        page_count=None,
        blocks=blocks,
        metadata={
            "row_count": len(table.rows),
            "data_rows": len(data),
            "column_count": len(names),
            "header": table.header,
            "header_row": table.header_row,
            "delimiter": table.delimiter,
            "encoding": table.encoding,
            "columns": profile(table),
            "extractor": "csv-stdlib",
        },
    )
