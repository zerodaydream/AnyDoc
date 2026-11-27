"""Check a line- or paragraph-located dataset: every gold answer must appear inside its gold lines (text) or
gold paragraphs (DOCX, by rendered paragraph index). CSV: each case's reference `gold_plan` is run through the query
engine and the gold answer must appear in its result, cited inside the gold rows.

Usage: uv run python -m eval.runners.check_gold eval/datasets/<name>.jsonl
"""

import json
import sys
from pathlib import Path

from eval.runners.run_eval import fetch_document, norm


def main() -> None:
    dataset = Path(sys.argv[1])
    meta = json.loads(dataset.with_suffix(".meta.json").read_text())
    path = fetch_document(meta["document"])
    if meta.get("format") == "csv":
        raise SystemExit(_check_csv(dataset, path))
    if meta.get("format") == "docx":
        from backend.tests.docxgen import _paragraph_texts

        units, key, base = _paragraph_texts(path.read_bytes()), "gold_paras", 0
    else:
        units, key, base = path.read_text(encoding="utf-8").split("\n"), "gold_lines", 1
    bad = 0
    for line in dataset.read_text().splitlines():
        case = json.loads(line)
        if not case["answerable"]:
            continue
        gold = norm(" ".join(" ".join(units[a - base : b - base + 1]) for a, b in case[key]))
        for alts in case["must_contain"]:
            if not any(norm(v) in gold for v in alts):
                bad += 1
                print(f"{case['id']}: none of {alts} in {key} {case[key]}")
    print("ok" if not bad else f"{bad} problems")
    raise SystemExit(1 if bad else 0)


def _check_csv(dataset: Path, path: Path) -> int:
    from backend.document_ir.models import ExtractLimits
    from backend.extraction.formats.csv.query import run_plan
    from eval.runners.run_eval import at_gold

    bad = 0
    for line in dataset.read_text().splitlines():
        case = json.loads(line)
        if not case["answerable"]:
            continue
        blocks = run_plan(path, case["gold_plan"], ExtractLimits(max_pages=500, max_chars=2_000_000))
        text = norm(" ".join(b.content for b in blocks))
        for alts in case["must_contain"]:
            if not any(norm(v) in text for v in alts):
                bad += 1
                print(f"{case['id']}: none of {alts} in the gold plan's result")
        if not all(at_gold(case, b.source_location.model_dump()) for b in blocks):
            bad += 1
            print(f"{case['id']}: gold plan reads rows outside gold_rows")
    print("ok" if not bad else f"{bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    main()
