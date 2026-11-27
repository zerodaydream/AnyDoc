"""Deterministic CSV samples for tests, the viewer parity fixtures and the synthetic eval set.

`sample_orders()` is a fictional bike shop's order log (agent-written, no real company): quoted values with commas,
doubled quotes, a multi-line note, thousands separators, blank cells. Gold answers for the eval set are computed here
with Decimal, independently of the query engine, so the eval checks the engine instead of trusting it.

Usage (writes the eval document + dataset and the viewer parity fixtures):
  uv run python -m backend.tests.csvgen
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

HEADER = [
    "Order ID",
    "Date",
    "Region",
    "Store",
    "Product",
    "Category",
    "Units",
    "Unit Price",
    "Total",
    "Status",
    "Notes",
]
STORES = [("West", "Pier Street"), ("East", "Old Mill"), ("North", "Summit Plaza"), ("West", "Harbor Mall"),
          ("South", "Bayfront"), ("East", "Riverside")]  # fmt: skip
PRODUCTS = [
    ("Trail Helmet", "Helmets", "89.00"),
    ("City Helmet", "Helmets", "64.50"),
    ("Road Bike Frame", "Frames", "1249.00"),
    ("Gravel Tires (pair)", "Tires", "118.00"),
    ("Commuter Lights", "Accessories", "42.75"),
    ("Bell", "Accessories", "9.99"),
    ("Carbon Fork", "Frames", "389.00"),
    ("Tube Pack", "Tires", "24.00"),
]
NOTES = {
    7: "Gift wrap, no invoice in box",
    19: 'Customer asked for "matte black" only',
    33: "Deliver after 5 pm\nside entrance",
    48: "Replaced under warranty, see ticket 5521",
    61: "Paid in two parts, second on pickup",
    90: 'Frame size "M", not "L"',
}
ROWS = 120


class _Lcg:
    """Tiny fixed generator so the file never depends on the random module's implementation."""

    def __init__(self, seed: int) -> None:
        self.x = seed

    def next(self) -> int:
        self.x = (self.x * 1103515245 + 12345) % 2**31
        return self.x >> 8


@dataclass(frozen=True)
class Order:
    row: int  # record number in the file (header = row 1)
    order_id: str
    day: date
    region: str
    store: str
    product: str
    category: str
    units: int
    price: Decimal
    total: Decimal
    status: str
    note: str


def orders() -> list[Order]:
    rnd = _Lcg(20261128)
    out = []
    for i in range(ROWS):
        region, store = STORES[i % len(STORES)] if i < len(STORES) else STORES[rnd.next() % len(STORES)]
        product, category, price = PRODUCTS[rnd.next() % len(PRODUCTS)]
        units = 1 + rnd.next() % 12
        roll = rnd.next() % 20
        status = "Cancelled" if roll < 2 else "Returned" if roll < 4 else "Pending" if roll < 6 else "Delivered"
        out.append(
            Order(
                row=i + 2,
                order_id=f"LB-{1001 + i}",
                day=date(2026, 1, 2) + timedelta(days=i * 100 // ROWS),
                region=region,
                store=store,
                product=product,
                category=category,
                units=units,
                price=Decimal(price),
                total=Decimal(price) * units,
                status=status,
                note=NOTES.get(i, ""),
            )
        )
    return out


def _q(v: str) -> str:
    return f'"{v.replace(chr(34), chr(34) * 2)}"' if any(c in v for c in ',"\n') else v


def sample_orders() -> bytes:
    lines = [",".join(HEADER)]
    for o in orders():
        cells = [o.order_id, o.day.isoformat(), o.region, o.store, o.product, o.category, str(o.units),
                 f"{o.price:.2f}", f"{o.total:,.2f}", o.status, o.note]  # fmt: skip
        lines.append(",".join(_q(c) for c in cells))
    return ("\r\n".join(lines) + "\r\n").encode()  # CRLF, as Excel writes CSV


# Parity fixtures: tricky files the viewer must read exactly as the backend does.
EDGE_FILES: dict[str, bytes] = {
    "quoting.csv": (
        b'Name,Comment,Score\n"Ada, Countess","She said ""hi""",9\n"ab"c,plain "quote" inside,7\n\n'
        b'Grace,"two\nlines",\n,,\nLinus,"",8,extra\n'
    ),
    "semicolon.csv": "Stadt;Einwohner;Fläche\nBerlin;3.850.809;891,7\nHamburg;1.945.532;755,2\n".encode(),
    "tabs.tsv": b"id\tname\tvalue\n1\talpha\t10\n2\tbeta\t20\n3\tgamma\t\n",
    "no-header.csv": b"10,20,30\n40,50,60\n70,80,90\n",
    "bom-crlf.csv": b"\xef\xbb\xbfCity|Country\r\nLyon|France\r\nPorto|Portugal",
    "cp1252.csv": "Caf\xe9,Price\nLatt\xe9,3.50\n".encode("cp1252"),
    "duplicate-names.csv": b"Name,Name,,Total\nA,B,C,1\nD,E,F,2\n",
    "single-column.csv": b"Fruit\napple\npear\n",
    "title-rows.csv": b'"Report title\nline two",,,\nA note about it,,,\n\n,Version,Date,Notes\n,7.1,2018-02-01,x\n,3.9-3.93,2012,y\n',
}


def parity_expectations() -> dict[str, Any]:
    from backend.extraction.formats.csv.table import column_names, find_header, parse, sniff
    from backend.extraction.formats.text.decode import decode_text

    out: dict[str, Any] = {}
    for name, data in {**EDGE_FILES, "orders.csv": sample_orders()}.items():
        text, encoding = decode_text(data)
        d = sniff(text)
        rows = parse(text, d)
        header = find_header(rows)
        out[name] = {
            "encoding": encoding,
            "delimiter": d,
            "headerIndex": header,
            "columns": column_names(rows, header),
            "rows": rows,
        }
    return out


def _fmt(d: Decimal) -> list[str]:
    """How a correct answer may write a computed number: as AnyDoc prints it, or with two decimals."""
    plain = format(d.normalize(), "f")
    if "." in plain:
        plain = plain.rstrip("0").rstrip(".")
    return list(dict.fromkeys([plain, f"{d:.2f}"]))


def _runs(rows: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for n in sorted(rows):
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return out


def eval_cases() -> list[dict[str, Any]]:
    """Questions with gold answers computed from `orders()` and gold rows. `gold_plan` is a reference TablePlan."""
    os_ = orders()
    all_rows = [o.row for o in os_]
    west = [o for o in os_ if o.region == "West"]
    cancelled = [o for o in os_ if o.status == "Cancelled"]
    helmets = [o for o in os_ if o.category == "Helmets"]
    march = [o for o in os_ if o.day.month == 3]
    biggest = max(os_, key=lambda o: o.total)
    by_store: dict[str, Decimal] = {}
    for o in os_:
        by_store[o.store] = by_store.get(o.store, Decimal(0)) + o.total
    top_store = max(by_store, key=lambda s: by_store[s])
    cheapest = min(o.price for o in os_)
    lookup = os_[41]
    noted = next(o for o in os_ if "warranty" in o.note)
    pending = os_[76]
    avg_helmet = sum((o.price for o in helmets), Decimal(0)) / len(helmets)
    revenue = sum((o.total for o in os_), Decimal(0))

    def plan(**q: Any) -> dict[str, Any]:
        return {"queries": [q]}

    def eq(column: str, value: str) -> dict[str, str]:
        return {"column": column, "op": "equals", "value": value}

    return [
        {"id": "ord-01", "question": "How many units were sold in the West region in total?", "answerable": True,
         "gold_rows": _runs([o.row for o in west]), "must_contain": [_fmt(Decimal(sum(o.units for o in west)))],
         "gold_plan": plan(compute="sum", column="Units", where=[eq("Region", "West")])},
        {"id": "ord-02", "question": "How many orders were cancelled?", "answerable": True,
         "gold_rows": _runs([o.row for o in cancelled]), "must_contain": [[str(len(cancelled))]],
         "gold_plan": plan(compute="count", where=[eq("Status", "Cancelled")])},
        {"id": "ord-03", "question": "What is the average unit price of helmets?", "answerable": True,
         "gold_rows": _runs([o.row for o in helmets]),
         "must_contain": [_fmt(avg_helmet.quantize(Decimal("0.0001")))],
         "gold_plan": plan(compute="average", column="Unit Price", where=[eq("Category", "Helmets")])},
        {"id": "ord-04", "question": "Which order has the largest total?", "answerable": True,
         "gold_rows": _runs([biggest.row]), "must_contain": [[biggest.order_id]],
         "gold_plan": plan(compute="rows", column="Total", order="descending", limit=1)},
        {"id": "ord-05", "question": f"What product was ordered in order {lookup.order_id}?", "answerable": True,
         "gold_rows": _runs([lookup.row]), "must_contain": [[lookup.product]],
         "gold_plan": plan(compute="rows", where=[eq("Order ID", lookup.order_id)])},
        {"id": "ord-06", "question": "Which store had the highest total sales?", "answerable": True,
         "gold_rows": _runs(all_rows), "must_contain": [[top_store]],
         "gold_plan": plan(compute="sum", column="Total", group_by=["Store"], order="descending", limit=3)},
        {"id": "ord-07", "question": "How many orders were placed in March 2026?", "answerable": True,
         "gold_rows": _runs(all_rows), "must_contain": [[str(len(march))]],
         "gold_plan": plan(compute="count", where=[{"column": "Date", "op": "at_least", "value": "2026-03-01"},
                                                   {"column": "Date", "op": "at_most", "value": "2026-03-31"}])},
        {"id": "ord-08", "question": "What is the total revenue across all orders?", "answerable": True,
         "gold_rows": _runs(all_rows), "must_contain": [_fmt(revenue)],
         "gold_plan": plan(compute="sum", column="Total")},
        {"id": "ord-09", "question": "Why was one order replaced under warranty, and which ticket covers it?",
         "answerable": True, "gold_rows": _runs([noted.row]), "must_contain": [["5521"]],
         "gold_plan": plan(compute="rows", where=[{"column": "Notes", "op": "contains", "value": "warranty"}])},
        {"id": "ord-10", "question": "How many different products appear in the orders?", "answerable": True,
         "gold_rows": _runs(all_rows), "must_contain": [[str(len({o.product for o in os_}))]],
         "gold_plan": plan(compute="count_distinct", column="Product")},
        {"id": "ord-11", "question": "What is the lowest unit price of any order?", "answerable": True,
         "gold_rows": _runs([o.row for o in os_ if o.price == cheapest]), "must_contain": [_fmt(cheapest)],
         "gold_plan": plan(compute="min", column="Unit Price")},
        {"id": "ord-12", "question": f"What is the status of order {pending.order_id}?", "answerable": True,
         "gold_rows": _runs([pending.row]), "must_contain": [[pending.status]],
         "gold_plan": plan(compute="rows", where=[eq("Order ID", pending.order_id)])},
        {"id": "ord-13", "question": "What is the email address of the customer behind order LB-1010?",
         "answerable": False},
        {"id": "ord-14", "question": "What was the profit margin on frames in 2025?", "answerable": False},
    ]  # fmt: skip


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    data = sample_orders()
    (root / "eval/data/public").mkdir(parents=True, exist_ok=True)
    (root / "eval/data/public/lumen-orders.csv").write_bytes(data)
    fixtures = root / "frontend/web/src/viewers/csv/fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    for name, raw in {**EDGE_FILES, "orders.csv": data}.items():
        (fixtures / name).write_bytes(raw)
    (fixtures / "expected.json").write_text(json.dumps(parity_expectations(), indent=1, ensure_ascii=False) + "\n")

    ds = root / "eval/datasets/lumen_csv_synthetic.jsonl"
    ds.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in eval_cases()))
    meta = {
        "synthetic": True,
        "format": "csv",
        "note": "Agent-written fictional order log and questions, generated by backend/tests/csvgen.py "
        "(deterministic), for the M5 CSV smoke baseline. Gold answers computed with Decimal in the generator, "
        "independently of the query engine. Not a substitute for the owner's evaluation set or real exports.",
        "document": {
            "generator": "backend.tests.csvgen:sample_orders",
            "filename": "lumen-orders.csv",
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "gold_rows_source": "1-based inclusive ranges of file records (header = row 1); checked with "
        "eval/runners/check_gold.py, which also runs each case's gold_plan through the query engine",
    }
    ds.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"{ROWS} orders, {len(eval_cases())} eval cases, {len(EDGE_FILES)} edge fixtures")


if __name__ == "__main__":
    main()
