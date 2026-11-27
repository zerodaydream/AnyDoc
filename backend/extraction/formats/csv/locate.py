"""Map a verified char span of a CSV block to cell ranges, from the IR only.

`format_metadata["segments"]` says where each piece of a block's content came from:
- `[content_start, content_end, row, col]`: one cell (row and table blocks, and rows listed by a query);
- `[content_start, content_end, group]`: a computed line, read from `format_metadata["groups"][group]`:
  `{"runs": [[row_a, row_b], ...], "cols": [col, ...], "rows": n, "truncated": bool}` (cols empty = whole rows).
`format_metadata["columns"]` holds the column names, so labels need no lookup.
"""

from typing import Any

from backend.document_ir.models import CsvLocation, CsvRegion

MAX_REGIONS = 300  # a computed result over thousands of scattered rows is shown by its first 300 runs


def _spans(cols: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for c in sorted(set(cols)):
        if out and c == out[-1][1] + 1:
            out[-1] = (out[-1][0], c)
        else:
            out.append((c, c))
    return out


def _covered(intervals: list[tuple[int, int]]) -> int:
    total, end = 0, 0
    for a, b in sorted(intervals):
        if b > end:
            total += b - max(a, end + 1) + 1
            end = b
    return total


def locate_csv(content: str, page: int | None, format_metadata: dict[str, Any], start: int, end: int) -> CsvLocation:
    segments: list[list[int]] = format_metadata["segments"]
    names: list[str] = format_metadata["columns"]
    width = max(1, len(names))
    hits = [s for s in segments if max(s[0], start) < min(s[1], end)]
    if not hits:  # the span sits on a separator or a "Row 12:" prefix: take its line's cells
        a = content.rfind("\n", 0, max(0, start)) + 1
        b = content.find("\n", start)
        b = len(content) if b < 0 else b
        hits = [s for s in segments if a <= s[0] < b] or [min(segments, key=lambda s: abs(s[0] - start))]

    cells: dict[int, list[int]] = {}
    blocks: list[tuple[int, int, list[int]]] = []  # (row_a, row_b, cols); cols empty = whole rows
    truncated, at_least = False, 0
    for s in hits:
        if len(s) == 4:
            cells.setdefault(s[2], []).append(s[3])
            continue
        g = format_metadata["groups"][s[2]]
        truncated = truncated or bool(g.get("truncated"))
        at_least = max(at_least, int(g["rows"]))
        blocks += [(a, b, list(g["cols"])) for a, b in g["runs"]]

    # Cells: one region per row and run of adjacent columns, merged down while the column runs stay the same.
    by_row = [(r, _spans(cols)) for r, cols in sorted(cells.items())]
    merged: list[list[Any]] = []
    for r, spans in by_row:
        if merged and merged[-1][1] == r - 1 and merged[-1][2] == spans:
            merged[-1][1] = r
        else:
            merged.append([r, r, spans])
    blocks += [(a, b, [c for s in spans for c in range(s[0], s[1] + 1)]) for a, b, spans in merged]

    regions: list[CsvRegion] = []
    for a, b, cols in blocks:
        for c0, c1 in _spans(cols) if cols else [(0, width - 1)]:
            regions.append(CsvRegion(row_start=a, row_end=b, col_start=c0, col_end=c1))
    if len(regions) > MAX_REGIONS:
        regions, truncated = regions[:MAX_REGIONS], True
    whole = any(not cols for _, _, cols in blocks)
    used = sorted({c for _, _, cols in blocks for c in cols})
    rows = max(_covered([(a, b) for a, b, _ in blocks]), at_least if truncated else 0)
    return CsvLocation(
        regions=regions,
        rows=rows,
        columns=[] if whole or len(used) == width else [names[c] for c in used if c < len(names)],
        truncated=truncated,
    )


def _names(cols: list[str]) -> str:
    cols = [c if len(c) <= 40 else c[:39] + "…" for c in cols]
    if len(cols) > 3:
        return f"{len(cols)} columns"
    return cols[0] if len(cols) == 1 else ", ".join(cols[:-1]) + " and " + cols[-1]


def label_csv(location: dict[str, Any]) -> str:
    regions = location["regions"]
    if not regions:
        return "table"
    a, b = min(r["row_start"] for r in regions), max(r["row_end"] for r in regions)
    rows = int(location.get("rows") or 0)
    if a == b:
        where = f"row {a:,}"
    elif rows == b - a + 1 and not location.get("truncated"):
        where = f"rows {a:,}–{b:,}"
    else:
        where = f"{rows:,} rows"
    cols = location.get("columns") or []
    return f"{where}, {_names(cols)}" if cols else where
