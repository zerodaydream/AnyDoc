# Technology evaluation

Research date: 2026-11-25. Machine: Apple M2, 8 GB RAM, macOS 26.5.1, Docker 28.2.2.
Versions below were read from PyPI/npm registry APIs on that date. Anything marked **unverified** was not confirmed from an official source.

---

## D1. PDF text extraction with bounding boxes

**Problem.** Extract text with per-character / per-word boxes and stable reading order, fast, low memory, with a licence safe for a hosted service.

**Alternatives.**

| Library | Version | Licence | Notes |
|---|---|---|---|
| PyMuPDF | 2.1 | AGPL-3.0 or commercial (Artifex) | Fast, rich API. AGPL network clause → source disclosure for a hosted service unless a commercial licence is bought. |
| pypdfium2 | 5.15.2 (2026-11-09) | BSD-3-Clause / Apache-2.0 (PDFium) | Char-level text + boxes, rendering. Word/line grouping is ours to write. |
| pdfplumber (pdfminer.six) | 0.11.11 (2026-11-21) | MIT | Word API, tables. Slow; spacing heuristics need tuning. |
| Docling | 2.152.0 (2026-11-23) | MIT (models have own licences) | Layout + table models; heavy (ML runtime). Footprint not stated on PyPI — **unverified** on 8 GB. |

**Test** (`scripts/research/bench_pdf_extract.py`, public PDFs: arXiv 1706.03762 15 pp, arXiv 1810.04805 6 pp, IRS W-9 form):

| Doc | PyMuPDF | pypdfium2 | pdfplumber (defaults) |
|---|---|---|---|
| attention.pdf | 6095 words, 2791 ms*, 191 MB | 6117 words, 881 ms, 60 MB | **2688 words** (words merged: `othertasksbyapplying…`), 2584 ms, 66 MB |
| bert.pdf | 10152, 306 ms, 61 MB | 9863, 357 ms, 44 MB | 7446, 1506 ms, 54 MB |
| irs_w9.pdf | 6280, 172 ms, 59 MB | 6272, 216 ms, 39 MB | 6303, 652 ms, 56 MB |

\* first-run, includes import/cold cache. Single run each; indicative, not a benchmark.

**Findings.** pypdfium2 matches PyMuPDF word counts within ~3 %, at similar speed and the lowest memory. pdfplumber's default `x_tolerance` merged words on a tightly-set paper — fixable, but it is 3–7× slower.

**Selection: pypdfium2** for char-level text, boxes and page rendering. We own word/line/block grouping, which we need anyway to keep an exact char-offset → box map for citations.
**Limitations.** Reading order for multi-column layouts and tables needs our own heuristics (column detection by x-gaps). Scanned pages have no text layer.
**Replacement / upgrade path.** Docling as an optional layout pass if M2 eval shows reading-order or table failures; PyMuPDF only with a commercial licence.
**OCR fallback.** Pages with no text layer are detected in M1 and marked `needs_ocr` (answerable = false, shown in UI). OCR engine is chosen in M10 (candidates: RapidOCR/ONNX, Tesseract — Tesseract is not installed on this machine and its Homebrew lib is currently broken).

Sources: <https://pypi.org/project/pypdfium2/> · <https://pymupdf.readthedocs.io/en/latest/about.html> · <https://pypi.org/project/docling/> · <https://pypi.org/project/pdfplumber/>

---

## D2. PDF viewer

**Alternatives.** `pdfjs-dist` 6.5.438 (Apache-2.0) directly · `react-pdf` 11.1.0 (MIT, wraps pdf.js) · PDFium-WASM / commercial SDKs (Nutrient, Apryse).
**Selection: `pdfjs-dist` directly.** We need virtualised pages, a custom highlight overlay, range loading and coordinate conversion; a wrapper hides those. pdf.js `PageViewport.convertToViewportRectangle` handles scale and rotation from PDF user space.
**Risk.** Extractor (PDFium) and viewer (pdf.js) are different engines. Both use PDF user space, so boxes should agree; M1 adds a test that renders highlight rects and checks they overlap pdf.js text-layer spans for the same text (target ≥ 95 % IoU match on sample PDFs).
**Replacement.** PDFium-WASM viewer if coordinate disagreement shows up.

---

## D3. Retrieval baseline components

| Component | Choice for M1 | Why | M2 will compare |
|---|---|---|---|
| Lexical | Postgres FTS (`tsvector`, GIN, `ts_rank_cd`) | Already in Postgres; no new service. Not true BM25. | `rank-bm25` 0.2.2 in-process; VectorChord-bm25 (check licence). ParadeDB `pg_search` is AGPL → excluded. |
| Dense | pgvector (`vector(768)`, HNSW cosine) | Brief requires no separate vector DB. 768 dims keeps index small; pgvector HNSW caps `vector` at 2000 dims. | 1536 dims via `halfvec` |
| Embeddings | `gemini-embedding-2`, `output_dimensionality=768` | No local RAM cost on an 8 GB machine; truncated vectors are auto-normalised for this model. Uses text prefixes (`task: search result \| query: …`) instead of `task_type`. | Local `fastembed` 0.9.1 (Apache-2.0, ONNX) e.g. bge-small for offline mode |
| Fusion | Reciprocal rank fusion, k=60 | Parameter-light, standard. | weighted fusion |
| Reranker | none in M1 | Must earn its place. | Local ONNX cross-encoder via fastembed vs `gemini-3.5-flash-lite` listwise rerank |

Embedding max input: 8,192 tokens per request; longer input is truncated (per docs summary — **verify** in code by counting tokens before embedding).

Sources: <https://ai.google.dev/gemini-api/docs/embeddings> (redirects to aistudio.google.com/docs/embeddings)

---

## D4. Job queue

| Option | Version | Licence | Infra | Notes |
|---|---|---|---|---|
| **procrastinate** | 3.12.0 (2026-11-19) | MIT | Postgres only | Verified in source: `cancel_job_by_id(abort=True)` + `JobContext.should_abort()`; `RetryStrategy` with `wait`, `linear_wait`, `exponential_wait`, `max_attempts`; `queueing_lock` and `lock` for idempotency/serialisation; async workers; periodic tasks; SQLAlchemy and Alembic contrib. Project asks for more maintainers. |
| arq | 0.28.0 (2026-04-16) | MIT | Redis | README: "In maintenance only mode". Excluded. |
| Celery / Dramatiq / RQ | — | BSD/LGPL/BSD | Redis or RabbitMQ | Add a broker the local version does not need. |

**Selection: procrastinate.** Meets retries, cancellation (including abort of running jobs), progress (we store it in our own `ingestion_jobs` table) and idempotency with zero extra infrastructure.
**Risk.** Maintainer bandwidth. Mitigation: everything goes through our `JobQueue` protocol; Dramatiq + Redis is the swap target.

---

## D5. Gemini models and pricing

Read from the official models, pricing and deprecations pages (ai.google.dev now redirects to aistudio.google.com/docs). SDK: `google-genai` 3.6.1 (Apache-2.0), imported as `from google import genai`.

| Role | Model ID (env var) | Status | Price per 1M tokens (paid, standard) |
|---|---|---|---|
| Answering | `gemini-3.8-flash` (`LLM_ANSWER_MODEL`) | Stable, no shutdown date | $0.75 in / $3.75 out until 2026-12-31; $1.50 / $7.50 from 2027-01-01 |
| Cheap high-volume | `gemini-3.5-flash-lite` (`LLM_FAST_MODEL`) | Stable, no shutdown date | $0.30 in / $2.50 out |
| Embeddings | `gemini-embedding-2` (`LLM_EMBED_MODEL`) | Stable (2026-04-22) | $0.20 text input |

Rejected: `gemini-2.5-*` (2.5-pro and 2.5-flash shut down 2026-12-01); `gemini-3.1-flash-lite` (shutdown 2027-05-07); `gemini-3.1-pro-preview` (preview); Gemini 4 family (no stable/preview badge on the models page — status **unverified**, and two of them are not on the free tier).

**Not stated on the pages and therefore unverified:** per-model input token limits for 3.x models; structured-output / JSON-schema support per model. **Mitigation:** the startup smoke check calls `models.get` for each configured ID, runs a tiny schema-constrained request against the answer and fast models, and fails loudly if either step fails. The context budget comes from `models.get` (`input_token_limit`), not from these docs.

**Cost estimate.** Full-document routing at 120k tokens ≈ $0.09 per question at the current answer-model input price. This is why the router budget is config and measured in M2.

Free tier note: free-tier content may be used to improve Google's products — do not use the free tier with private documents.

Sources: <https://ai.google.dev/gemini-api/docs/models> · <https://ai.google.dev/gemini-api/docs/pricing> · <https://ai.google.dev/gemini-api/docs/deprecations>

---

## D6. LangSmith integration

`langsmith` 0.16.2 (MIT). Verified from the installed package source:
- `Client(hide_inputs=..., hide_outputs=..., hide_metadata=..., anonymizer=...)`; `hide_*` accept `bool` or a callable. Env fallbacks `LANGSMITH_HIDE_INPUTS`, `LANGSMITH_HIDE_OUTPUTS`, `LANGSMITH_HIDE_METADATA`.
- `langsmith.anonymizer.create_anonymizer` and `create_secret_anonymizer` exist.
- `@traceable(client=...)` works on non-LangChain code; per-function `process_inputs` / `process_outputs` override client-level processors.
- `langsmith.wrappers.wrap_gemini` exists and is marked **BETA**.

**Selection.** Our `@traced` wrapper over `@traceable` with a client configured `hide_inputs=True, hide_outputs=True` unless `TRACE_CONTENT=true`, plus `create_secret_anonymizer` always on. Do not use `wrap_gemini` (beta; would capture prompts). Metadata we attach is IDs, scores, timings, token counts — never content.

Sources: <https://docs.langchain.com/langsmith/mask-inputs-outputs> · <https://docs.langchain.com/langsmith/redact-secrets>

---

## Supporting stack (versions at research date)

Backend: FastAPI 0.165.0 · Pydantic 2.14.4 · SQLAlchemy 2.1.9 · Alembic 1.20.1 · psycopg 3.3.9 (LGPL-3.0, dynamic use is fine) · onnxruntime 1.32.0 (later).
Frontend: React 19.3.1 · Vite 8.3.8 · Tailwind 4.3.5 · react-resizable-panels 4.24.2 · Zustand 5.1.0 · TanStack Query 5.108.4 · TanStack Virtual 3.14.28 · lucide-react 1.79.0 (ISC) · pdfjs-dist 6.5.438.
Postgres: `pgvector/pgvector:pg17` image (tag to be pinned in M1 after pulling).

## Environment findings that affect later milestones

- **8 GB RAM.** Docker Desktop should get ~4 GB. Local ML (reranker, OCR, ASR) must be small and quantised; Parakeet 0.6B int8 (~622 MB encoder) is feasible, Whisper large-v3 is likely not alongside the rest — measured at M11.
- **ffmpeg is broken** on this machine (`Library not loaded: /opt/homebrew/opt/tesseract/lib/libtesseract.5.dylib`). Fix before M11: `brew reinstall tesseract ffmpeg`.
- **LibreOffice not installed.** Needed only if DOCX/PPTX go the convert-to-PDF route (M4/M9).
- **Docker daemon was not running** at research time.
