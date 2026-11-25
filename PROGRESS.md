# Progress

Read this first every session. Update it last.

## Current state (2026-11-25)
- **M0 — Inspect, research, document: complete, awaiting owner review.**
- M1 not started. Do not start until the owner approves the M0 plan.
- M2 blocked until the owner supplies evaluation documents in `eval/data/`.

## Repository state at M0 start
Empty directory, not a git repository. Nothing to reuse. Initialised git (`main`).

## Done
- Brief copied to `docs/MASTER_PROMPT.md`.
- `CLAUDE.md`, `MISSION.md`, `ARCHITECTURE.md`, `README.md`, `docs/TECHNOLOGY_EVALUATION.md`, `docs/DESIGN.md`, `docs/EVAL_TARGETS.md` (placeholder), ADR-0001..0003, `.env.example`.
- PDF extractor bench: `scripts/research/bench_pdf_extract.py` (results in TECHNOLOGY_EVALUATION D1).

## Decisions (details in docs/TECHNOLOGY_EVALUATION.md)
| # | Decision | Choice |
|---|---|---|
| D1 | PDF extraction | pypdfium2 + own grouping (PyMuPDF excluded: AGPL) |
| D2 | PDF viewer | pdfjs-dist 6.5.x directly, custom overlay |
| D3 | Retrieval baseline | Postgres FTS + pgvector(640) + RRF; local `harrier-oss-v1-270m` embeddings; no reranker until M2 proves one |
| D4 | Job queue | procrastinate (Postgres, no Redis) |
| D5 | Gemini models | answer `gemini-3.8-flash`, fast `gemini-3.5-flash-lite` (no 3.8 Flash-Lite text model exists), env-configured; no cost cap |
| Run | Dev mode | Postgres in Docker; api + worker native on macOS; full Compose stack also maintained |
| D6 | Tracing | LangSmith via own `@traced` wrapper, inputs/outputs hidden by default; no `wrap_gemini` |
| UI | Design | Always opens dark, light toggle remembered; Source Serif 4 / Hanken Grotesk; name "AnyDoc"; `docs/DESIGN.md` |
| Licence | Policy | Private use now, may sell later → no AGPL/SSPL/non-commercial deps |

## Owner answers (2026-11-25)
Private now, maybe host/sell later · local embeddings, lightest best-retrieval model · Gemini 3.8 Flash family · no cost cap · Postgres-only Docker in dev, full Compose kept · always dark · name AnyDoc final.

## Unverified (must be checked in M1 code)
- Per-model input token limits for Gemini 3.x (read via `models.get` at startup).
- Structured output + streaming structured output support on chosen models (smoke test).
- pdfium ↔ pdf.js coordinate agreement (test).
- harrier-oss-v1-270m speed and peak RAM on this Mac (M1); retrieval quality vs alternatives (M2).
- Owner's Gemini key is on a billed paid tier (AI Pro subscription does not include API access).

## Blocked / waiting on owner
- Docker Desktop daemon not running (needed for M1).
- `GEMINI_API_KEY`, `LANGSMITH_API_KEY` + project name (M1 uses `FakeProvider` and no-op tracer until then).
- Evaluation documents + questions (blocks M2).
- Environment: ffmpeg broken (missing libtesseract), LibreOffice absent — only matters at M4/M9/M11.

## Next
M1 — Foundation + PDF vertical slice (plan in ARCHITECTURE.md), after owner review.
