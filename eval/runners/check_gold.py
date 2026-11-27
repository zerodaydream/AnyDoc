"""Check a line- or paragraph-located dataset: every gold answer must appear inside its gold lines (text) or
gold paragraphs (DOCX, by rendered paragraph index).

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


if __name__ == "__main__":
    main()
