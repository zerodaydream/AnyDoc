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
