# Evaluation targets

**Targets not set yet.** Per the brief (§11) they are proposed with the owner after a baseline on the owner's real documents, then recorded here and used to gate milestones. M2 is blocked until those documents arrive in `eval/data/`.

## Baseline log

### 2026-11-25 — M1 smoke baseline (SYNTHETIC, not a target-setting run)
- Dataset: `eval/datasets/attention_synthetic.jsonl` — 14 agent-written questions on the public "Attention Is All You Need" PDF (11 answerable, 3 unanswerable incl. one prompt-injection).
- Config: `gemini-3.5-flash-lite` (answer model from `.env`), full-context route (24.8k input tokens), local `harrier-oss-v1-270m` embeddings.
- Results file: `eval/results/attention_synthetic-20261125T125718Z.json`

| Metric | Value |
|---|---|
| Answer correctness (gold substrings) | 1.000 (11/11) |
| Citation page accuracy | 0.909 (10/11) |
| False abstention rate | 0.000 |
| Correct abstention (unanswerable) | 1.000 (3/3) |
| Errors after retries | 0 |
| p50 latency (wall) | 2.0 s |

The single page "miss" (att-10) was a gold-label error: the answer correctly added a second fact cited on p. 10. Gold pages were corrected afterwards to `[8, 10]`; the recorded number above is left as measured.

Caveats: one tiny, easy, synthetic set; the full-document route means hybrid retrieval was not exercised. This says the pipeline works end to end, not that accuracy is known.

Metrics that will get targets: retrieval recall@k and MRR · answer correctness · citation location accuracy · citation support · numeric correctness · abstention precision/recall · p50/p95 latency · tokens and cost per question · (M11) WER and word-timing error.

### 2026-11-26 — M3 TXT/Markdown datasets (SYNTHETIC), live baseline pending
- `eval/datasets/apache_txt_synthetic.jsonl` — 14 questions on the Apache License 2.0 text (11 answerable, 3 unanswerable incl. one prompt-injection).
- `eval/datasets/zustand_md_synthetic.jsonl` — 13 questions on the zustand v5.1.0 README (11 answerable, 2 unanswerable).
- Gold locations are 1-based line ranges; `eval/runners/check_gold.py` confirms every gold answer appears inside its gold lines (both pass).
- The runner now scores **citation location accuracy** (gold pages for PDF, overlapping gold lines for text) and opens a fresh conversation per question.
- **Not yet run against Gemini**: the agent's session had no API key. The pipeline was exercised end to end with the offline fake model only (scores meaningless, not recorded).
