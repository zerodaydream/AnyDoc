"""Check a line-located dataset: every gold answer must appear inside its gold lines.

Usage: uv run python -m eval.runners.check_gold eval/datasets/<name>.jsonl
"""

import json
import sys
from pathlib import Path

from eval.runners.run_eval import fetch_document, norm


def main() -> None:
    dataset = Path(sys.argv[1])
    meta = json.loads(dataset.with_suffix(".meta.json").read_text())
    lines = fetch_document(meta["document"]).read_text(encoding="utf-8").split("\n")
    bad = 0
    for line in dataset.read_text().splitlines():
        case = json.loads(line)
        if not case["answerable"]:
            continue
        gold = norm(" ".join(" ".join(lines[a - 1 : b]) for a, b in case["gold_lines"]))
        for alts in case["must_contain"]:
            if not any(norm(v) in gold for v in alts):
                bad += 1
                print(f"{case['id']}: none of {alts} in lines {case['gold_lines']}")
    print("ok" if not bad else f"{bad} problems")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
