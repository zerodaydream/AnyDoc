"""CSV -> rows of cells. Shared by extraction and table queries; the viewer (viewers/csv/csv.ts) mirrors it exactly.

Rules (identical in both languages, checked by a parity fixture):
- Bytes decode like TXT (formats/text/decode.py): BOM -> UTF-8 -> Windows-1252, newlines normalised to "\\n".
- Tokenising (RFC 4180, as Python's csv module reads it with strict=False): a field that starts with `"` is quoted;
  `""` inside it is one quote; text after the closing quote up to the delimiter is kept (`"ab"c` -> `abc`). A quote
  inside an unquoted field is literal. A blank line is an empty record. Unlike the csv module, a quote that is never
  closed fails the file instead of swallowing the rest of it.
- Delimiter: the candidate (`,` tab `;` `|`) whose first 50 records agree best on one field count of 2 or more.
- Header: the first record is a header when at least half its cells are filled, none is a number, there is at
  least one more record, and no name reappears as a value in its column in the next 50 records. (Empty and repeated
  names are allowed: pandas writes an empty first name for its index. They become "Column A", "Name (2)".)
- Rows are numbered by record, from 1, header included, blank lines included: what a spreadsheet shows.

Pure functions, no DB, no network: runs inside the parsing sandbox.
"""

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from backend.core.errors import InvalidFile
from backend.extraction.formats.text.decode import decode_text

DELIMITERS = (",", "\t", ";", "|")
SNIFF_CHARS = 65536
SNIFF_RECORDS = 50
MAX_COLUMNS = 1000
_QUOTED = re.compile(r'"([^"]*(?:""[^"]*)*)"')
# A number as people write it in tables: sign, currency, thousands commas, decimals, exponent, percent, (negative).
NUMERIC = re.compile(r"^[-+(]?[$€£¥₹]?(?:[0-9][0-9,]*(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?%?\)?$")
_CURRENCY = re.compile(r"[$€£¥₹]")
ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}")


def parse(text: str, delimiter: str, *, partial: bool = False) -> list[list[str]]:
    """Records of `text`. `partial`: the text is a cut-off sample, so an unclosed quote just ends it."""
    unquoted = re.compile(f"[^{re.escape(delimiter)}\\n]*")
    rows: list[list[str]] = []
    row: list[str] = []
    i, n = 0, len(text)
    while i < n:
        quoted = text[i] == '"'
        if quoted:
            m = _QUOTED.match(text, i)
            if m is None:
                if partial:
                    return rows
                raise InvalidFile(
                    "malformed_csv",
                    f"A quoted value in row {len(rows) + 1:,} is never closed, so the rows after it can't be read.",
                )
            value = m.group(1).replace('""', '"')
            i = m.end()
        else:
            value = ""
        rest = unquoted.match(text, i)
        assert rest is not None  # matches the empty string at worst
        value += rest.group()
        i = rest.end()
        row.append(value)
        if i < n and text[i] == delimiter:
            i += 1
            if i == n:  # "a,b," at the very end: the record ends with an empty field
                row.append("")
            continue
        rows.append([] if len(row) == 1 and not quoted and not row[0] else row)
        row = []
        i += 1  # past the "\n"; a final newline adds no record
    if row:  # the text ended right after a delimiter
        rows.append(row)
    return rows


def sniff(text: str) -> str:
    sample = text[:SNIFF_CHARS]
    cut = len(text) > SNIFF_CHARS
    best, best_score = ",", (0.0, 0)
    for d in DELIMITERS:
        recs = parse(sample, d, partial=True)
        if cut:
            recs = recs[:-1]  # the last record may be cut off
        recs = [r for r in recs if r][:SNIFF_RECORDS]
        if not recs:
            continue
        counts = Counter(len(r) for r in recs)
        mode = max(counts, key=lambda w: (counts[w], w))
        if mode < 2:
            continue
        score = (counts[mode] / len(recs), mode)
        if score > best_score:
            best, best_score = d, score
    return best


def has_header(rows: list[list[str]]) -> bool:
    if not rows or not rows[0]:
        return False
    first = [c.strip() for c in rows[0]]
    filled = [c for c in first if c]
    if 2 * len(filled) < len(first) or any(NUMERIC.match(c) for c in filled):
        return False
    body = [r for r in rows[1 : SNIFF_RECORDS + 1] if r]
    if not body:
        return False
    return not any(name and k < len(r) and r[k].strip() == name for k, name in enumerate(first) for r in body)


def column_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        s = chr(65 + rem) + s
    return s


def column_names(rows: list[list[str]], header: bool) -> list[str]:
    width = max((len(r) for r in rows), default=0)
    head = rows[0] if header else []
    names: list[str] = []
    seen: dict[str, int] = {}
    for i in range(width):
        base = (" ".join(head[i].split()) if i < len(head) else "") or f"Column {column_letter(i)}"
        seen[base] = seen.get(base, 0) + 1
        names.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
    return names


def to_number(s: str) -> float | None:
    t = s.strip()
    if not t or not NUMERIC.match(t):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = _CURRENCY.sub("", t.strip("()")).replace(",", "").rstrip("%")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def decimals(s: str) -> int:
    """Digits after the decimal point as written ("1,200.50" -> 2), for formatting results like the source."""
    t = s.strip().split("e")[0].split("E")[0]
    return len(t.split(".", 1)[1].rstrip("%)")) if "." in t else 0


@dataclass(slots=True)
class Table:
    rows: list[list[str]]  # rows[i] is record i + 1; a blank line is []
    header: bool
    columns: list[str]
    delimiter: str
    encoding: str

    def data_rows(self) -> list[tuple[int, list[str]]]:
        """(row number, cells) of every non-blank record below the header."""
        start = 1 if self.header else 0
        return [(i + 1, r) for i, r in enumerate(self.rows[start:], start) if r]


def read_table(path: Path, max_chars: int) -> Table:
    text, encoding = decode_text(path.read_bytes())
    if len(text) > max_chars:
        raise InvalidFile("too_long", f"This file has {len(text):,} characters; the limit is {max_chars:,}.")
    delimiter = sniff(text)
    rows = parse(text, delimiter)
    header = has_header(rows)
    columns = column_names(rows, header)
    if len(columns) > MAX_COLUMNS:
        raise InvalidFile("too_wide", f"This file has {len(columns):,} columns; the limit is {MAX_COLUMNS:,}.")
    table = Table(rows, header, columns, delimiter, encoding)
    if not table.data_rows():
        raise InvalidFile("no_rows", "This CSV file has no data rows.")
    return table
