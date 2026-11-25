# Progress

Read this first every session. Update it last.

## Current state (2026-11-25)
- M0 — done (research, plan; owner answered clarifications).
- **M1 — Foundation + PDF vertical slice: built and tested, awaiting owner review.**
- M2 — blocked until the owner supplies evaluation documents in `eval/data/`.

## M1 done
- Backend (FastAPI, SQLAlchemy async, Alembic, procrastinate, pypdfium2, google-genai, sentence-transformers):
  upload (raw streamed body, size cap, ext + magic bytes) → immutable content-addressed storage → queue →
  sandboxed extraction (child process, timeout, RLIMIT_AS on Linux) → IR blocks with word boxes →
  chunks + FTS + local embeddings → ready. Cancel (incl. abort of running jobs) and retry.
- Answering: router (full document ≤ 120k tokens, else FTS + pgvector RRF + neighbour expansion), streamed
  structured output, per-segment citation validation (exact → normalised → fuzzy ≥ 90; numbers must appear in
  cited text), IR-derived highlight rects, abstain with closest passages, one automatic restart on mid-stream
  provider failure, unvalidated text retracted on failure.
- Frontend (React 19, Vite, Tailwind 4, Zustand, TanStack Query, react-resizable-panels 4, pdf.js 6):
  split workspace (persisted, collapsible, keyboard), mobile tabs, upload/processing/failed states, streaming
  chat, citation numerals + evidence rows, click-to-highlight with multi-region stepping, find, zoom,
  dark default + light toggle.
- Observability: `@traced` LangSmith wrapper (inputs/outputs hidden by default), JSON logs with request ids,
  token/latency usage per answer, audit log rows.
- Compose: postgres (dev default) + full profile (migrate/api/worker/web). Web image builds.

## Tests (all green 2026-11-25)
- Backend: 41 pytest (extraction incl. 4 rotations × CropBox, malformed/truncated/no-text/page-limit, sandbox
  timeout/crash, normaliser, fabricated + foreign citations, numeric check, streaming events, owner scoping,
  range requests, cancel/retry/abort, mid-stream failure + restart, config parsing). ruff + mypy --strict clean.
- Frontend: 14 vitest (SSE parser, answer reducer incl. reset, geometry incl. rotation, registry, WCAG token
  contrast, citation click → viewer state, retraction, abstain, low-confidence). tsc + eslint clean.
- E2E: `frontend/web/e2e/smoke.mjs` (real stack, real Gemini, Brave headless): ask → click citation →
  highlight on the cited page; dark, light and mobile screenshots reviewed.
- Eval: synthetic smoke baseline recorded in `docs/EVAL_TARGETS.md`.

## Decisions made during M1 (beyond M0)
| Decision | Why |
|---|---|
| PDF rects stored in raw PDF user space (not CropBox-relative) | pdf.js applies CropBox + rotation itself; zero conversion code; verified by tests under 4 rotations × CropBox |
| Model sees per-request block aliases `b0..bn` | Live test: Gemini truncated `pdf:8:7:38b2d058` → citations rejected. Aliases fixed it and cut prompt ~17% |
| Embeddings in bf16 on MPS, fp32 on CPU | fp16 on MPS returned wrong rankings for harrier (measured); bf16 correct and fastest |
| Ingestion state folded into `document_versions` (no separate jobs table) | One job per version; less code; procrastinate keeps its own job table |
| Progress via 1 s polling, not SSE | Simpler; fine for one active document |
| Gemini startup check: 404/403 fail loudly; 503 overload only warns | Models were overloaded during testing; existence is still verified via `models.get` |
| shadcn/ui not adopted | UI needs ~6 primitives; hand-written with design tokens is smaller |

## Measured
- Ingest, Attention paper (15 pp, 461 blocks, 48 chunks): 8 s end to end on MPS.
- harrier-oss-v1-270m: MPS bf16 9.0 chunks/s, 879 MB peak RSS; CPU fp32 0.6 chunks/s (Docker mode is slow).
- Answer: ~2 s p50, ~24.8k input tokens on full-context route.
- Verified via API: `gemini-3.6-flash`, `gemini-3.5-flash-lite` input limit 1,048,576 tokens; structured output works on both. `gemini-3.8-flash` exists but returned 503 (overloaded) during all M1 tests — structured output on it still unverified.

## Known limitations
- Figure labels in papers can be detected as headings (affects section_path only).
- Reading order is PDFium content order + line grouping; complex multi-column/table layouts untested on real samples.
- Scanned PDFs fail with `no_text_layer` (OCR is M10). Encrypted PDFs fail with a clear message (no test fixture).
- macOS ignores RLIMIT_AS: parser memory cap is enforced only in Linux containers; timeout applies everywhere.
- No PDF thumbnails yet. No Playwright test runner — a playwright-core script using an installed browser.
- Backend Docker image not built yet (torch layer ~1 GB download) — awaiting owner OK.
- Hybrid retrieval exercised only in tests (live docs fit the full-context budget).

## Blocked / waiting on owner
- Evaluation documents + questions (blocks M2).
- `LANGSMITH_API_KEY` (tracing is a no-op until set).
- OK to build the backend Docker image.

## Next
M2 — retrieval quality, after owner review of M1 and evaluation documents.
