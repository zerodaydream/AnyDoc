"""Local evaluation runner (no LangSmith needed). Talks to a running API.

Usage: uv run python -m eval.runners.run_eval eval/datasets/attention_synthetic.jsonl [--api http://localhost:8000]
Writes eval/results/<dataset>-<UTC time>.json and prints a summary.
"""

import argparse
import hashlib
import json
import statistics
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]


def fetch_document(meta: dict[str, Any]) -> Path:
    path = ROOT / "data" / "public" / meta["filename"]
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(meta["url"], path)  # noqa: S310 - fixed https URL from dataset meta
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != meta["sha256"]:
        raise SystemExit(f"{path} sha256 mismatch: got {digest}")
    return path


def ask(api: httpx.Client, doc_id: str, question: str, tries: int = 3) -> dict[str, Any]:
    for attempt in range(tries):
        events: list[tuple[str, dict[str, Any]]] = []
        t = time.perf_counter()
        with api.stream("POST", f"/api/documents/{doc_id}/messages", json={"question": question}, timeout=180) as r:
            buf = ""
            for chunk in r.iter_text():
                buf += chunk
                while "\n\n" in buf:
                    frame, buf = buf.split("\n\n", 1)
                    lines = dict(line.split(": ", 1) for line in frame.splitlines())
                    events.append((lines["event"], json.loads(lines["data"])))
        if events and events[-1][0] == "done":
            break
        time.sleep(5 * (attempt + 1))  # provider overload: back off and retry
    text: dict[int, str] = {}
    retracted: set[int] = set()
    cites: list[dict[str, Any]] = []
    for kind, d in events:
        if kind == "reset":
            text, retracted, cites = {}, set(), []
        elif kind == "text_delta":
            text[d["segment"]] = text.get(d["segment"], "") + d["text"]
        elif kind == "segment_retracted":
            retracted.add(d["segment"])
        elif kind == "citation":
            cites.append(d["citation"])
    last_kind, last = events[-1] if events else ("error", {})
    return {
        "status": last.get("status", "error") if last_kind == "done" else "error",
        "answer": " ".join(t for i, t in sorted(text.items()) if i not in retracted),
        "citations": [{"page": c["page"], "match": c["match"], "quote": c["quote"][:200]} for c in cites],
        "retracted": len(retracted),
        "usage": last.get("usage", {}),
        "wall_ms": int((time.perf_counter() - t) * 1000),
    }


def norm(s: str) -> str:
    return s.casefold().replace(",", "")


def score(case: dict[str, Any], res: dict[str, Any]) -> dict[str, Any]:
    answered = res["status"] in ("answered", "partial", "conflicting_evidence") and res["citations"]
    if not case["answerable"]:
        return {"abstain_correct": not answered}
    correct = bool(answered) and all(any(norm(v) in norm(res["answer"]) for v in alts) for alts in case["must_contain"])
    pages_ok = bool(answered) and all(c["page"] in case["gold_pages"] for c in res["citations"])
    return {"answer_correct": correct, "citation_pages_ok": pages_ok, "abstained": not answered}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--api", default="http://localhost:8000")
    args = ap.parse_args()
    meta = json.loads(args.dataset.with_suffix(".meta.json").read_text())
    cases = [json.loads(line) for line in args.dataset.read_text().splitlines() if line.strip()]
    pdf = fetch_document(meta["document"])

    with httpx.Client(base_url=args.api) as api:
        doc = api.post("/api/documents", params={"filename": pdf.name}, content=pdf.read_bytes(), timeout=120).json()
        while doc["status"] not in ("ready", "failed", "cancelled"):
            time.sleep(1)
            doc = api.get(f"/api/documents/{doc['id']}").json()
        if doc["status"] != "ready":
            raise SystemExit(f"ingest {doc['status']}: {doc['error']}")
        rows = []
        for case in cases:
            res = ask(api, doc["id"], case["question"])
            rows.append({"id": case["id"], "question": case["question"], **res, **score(case, res)})
            print(f"{case['id']}: {res['status']:<22} {score(case, res)}")

    ans = [r for r, c in zip(rows, cases, strict=True) if c["answerable"]]
    una = [r for r, c in zip(rows, cases, strict=True) if not c["answerable"]]
    model = next((r["usage"].get("model") for r in rows if r["usage"].get("model")), "unknown")
    summary = {
        "dataset": args.dataset.name,
        "synthetic": meta.get("synthetic", False),
        "model": model,
        "n": len(rows),
        "answer_correct": round(sum(r["answer_correct"] for r in ans) / len(ans), 3),
        "citation_page_accuracy": round(sum(r["citation_pages_ok"] for r in ans) / len(ans), 3),
        "false_abstain_rate": round(sum(r["abstained"] for r in ans) / len(ans), 3),
        "abstain_correct": round(sum(r["abstain_correct"] for r in una) / max(1, len(una)), 3),
        "errors": sum(r["status"] == "error" for r in rows),
        "retracted_segments": sum(r["retracted"] for r in rows),
        "p50_latency_ms": statistics.median(r["wall_ms"] for r in rows),
        "avg_input_tokens": round(statistics.mean(r["usage"].get("input_tokens", 0) for r in rows)),
    }
    out = ROOT / "results" / f"{args.dataset.stem}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2))
    print(f"written: {out.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()
