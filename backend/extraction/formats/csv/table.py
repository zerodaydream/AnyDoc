"""CSV -> rows of cells. Shared by extraction and table queries; the viewer (viewers/csv/csv.ts) mirrors it exactly.

Rules (identical in both languages, checked by a parity fixture):
- Bytes decode like TXT (formats/text/decode.py): BOM -> UTF-8 -> Windows-1252, newlines normalised to "\\n".
- Tokenising (RFC 4180, as Python's csv module reads it with strict=False): a field that starts with `"` is quoted;
  `""` inside it is one quote; text after the closing quote up to the delimiter is kept (`"ab"c` -> `abc`). A quote
  inside an unquoted field is literal. A blank line is an empty record. Unlike the csv module, a quote that is never
  closed fails the file instead of swallowing the rest of it.
- Delimiter: the candidate (`,` tab `;` `|`) whose first 50 records agree best on one field count of 2 or more.
- Header: a record is a header when at least half its cells are filled, none is a number, there is at least one
  more record, and no name reappears as a value in its column in the next 50 records. (Empty and repeated names are
  allowed: pandas writes an empty first name for its index. They become "Column A", "Name (2)".)
  The first record is tried first. When it isn't a header, title lines above the table (blank records, or records
  with fewer than 2 or fewer than half of the table's cells filled, at most 10) are skipped and the next record is
  tried. Those title lines are the preamble: kept and shown, but not data rows.
- Rows are numbered by record, from 1, header and preamble included, blank lines included: what a spreadsheet shows.
- A column is a number column when at least half its filled cells are numbers (NUMBER_SHARE); computations use the
  numbers and report the other cells they left out.

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
MAX_PREAMBLE = 10
NUMBER_SHARE = 0.5
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


def _sparse(row: list[str], width: int) -> bool:
    """A title-like record: blank, or too few cells filled to be a header of a table this wide."""
    filled = sum(1 for c in row if c.strip())
    return filled < 2 or 2 * filled < width


def find_header(rows: list[list[str]]) -> int | None:
    """Index of the header record, or None. 0 unless title lines sit above the table (see the module rules)."""
    if has_header(rows):
        return 0
    width = max((len(r) for r in rows[: SNIFF_RECORDS + MAX_PREAMBLE]), default=0)
    if width < 2:
        return None
    i = 0
    while i < min(len(rows), MAX_PREAMBLE) and _sparse(rows[i], width):
        i += 1
    return i if 0 < i < len(rows) and has_header(rows[i:]) else None


def column_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        s = chr(65 + rem) + s
    return s


def column_names(rows: list[list[str]], header: int | None) -> list[str]:
    """Names from the header record at index `header` (None: no header), "Column A"... where a name is missing."""
    width = max((len(r) for r in rows), default=0)
    head = rows[header] if header is not None else []
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
    header_index: int | None  # index in rows of the header record; None: no header
    columns: list[str]
    delimiter: str
    encoding: str

    @property
    def header(self) -> bool:
        return self.header_index is not None

    @property
    def header_row(self) -> int | None:
        """Row number of the header (1-based, as the viewer shows it)."""
        return None if self.header_index is None else self.header_index + 1

    def head(self) -> list[str]:
        return self.rows[self.header_index] if self.header_index is not None else []

    def preamble_rows(self) -> list[tuple[int, list[str]]]:
        """(row number, cells) of the non-blank title lines above the header."""
        return [(i + 1, r) for i, r in enumerate(self.rows[: self.header_index or 0]) if r]

    def data_rows(self) -> list[tuple[int, list[str]]]:
        """(row number, cells) of every non-blank record below the header."""
        start = 0 if self.header_index is None else self.header_index + 1
        return [(i + 1, r) for i, r in enumerate(self.rows[start:], start) if r]


def mostly_numbers(values: list[str]) -> bool:
    """Filled cells of one column: enough of them are numbers to compute with (the rest are reported, not used)."""
    filled = [v for v in values if v.strip()]
    return bool(filled) and sum(1 for v in filled if to_number(v) is not None) >= NUMBER_SHARE * len(filled)


def read_table(path: Path, max_chars: int) -> Table:
    text, encoding = decode_text(path.read_bytes())
    if len(text) > max_chars:
        raise InvalidFile("too_long", f"This file has {len(text):,} characters; the limit is {max_chars:,}.")
    delimiter = sniff(text)
    rows = parse(text, delimiter)
    header = find_header(rows)
    columns = column_names(rows, header)
    if len(columns) > MAX_COLUMNS:
        raise InvalidFile("too_wide", f"This file has {len(columns):,} columns; the limit is {MAX_COLUMNS:,}.")
    table = Table(rows, header, columns, delimiter, encoding)
    if not table.data_rows():
        raise InvalidFile("no_rows", "This CSV file has no data rows.")
    return table
