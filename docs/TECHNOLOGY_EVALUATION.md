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

**Licence context (owner, 2026-11-25):** private use now, may host and sell later. AGPL stays excluded so selling later needs no rewrite.

**Selection: pypdfium2** for char-level text, boxes and page rendering. We own word/line/block grouping, which we need anyway to keep an exact char-offset → box map for citations.
**Limitations.** Reading order for multi-column layouts and tables needs our own heuristics (column detection by x-gaps). Scanned pages have no text layer.
**Replacement / upgrade path.** Docling as an optional layout pass if M2 eval shows reading-order or table failures; PyMuPDF only with a commercial licence.
**OCR fallback.** Pages with no text layer are detected in M1 and marked `needs_ocr` (answerable = false, shown in UI). OCR engine is chosen in M10 (candidates: RapidOCR/ONNX, Tesseract — Tesseract is not installed on this machine and its Homebrew lib is currently broken).

Sources: <https://pypi.org/project/pypdfium2/> · <https://pymupdf.readthedocs.io/en/latest/about.html> · <https://pypi.org/project/docling/> · <https://pypi.org/project/pdfplumber/>

---

## D2. PDF viewer

**Alternatives.** `pdfjs-dist` 6.5.438 (Apache-2.0) directly · `react-pdf` 11.1.0 (MIT, wraps pdf.js) · PDFium-WASM / commercial SDKs (Nutrient, Apryse).
**Selection: `pdfjs-dist` directly** (uses `pdf_viewer.mjs` `PDFViewer` for virtualised pages, text layer and find). Note: pdf.js 6 removed `convertToViewportRectangle`; we convert two corners with `convertToViewportPoint` (verified in M1). We need virtualised pages, a custom highlight overlay, range loading and coordinate conversion; a wrapper hides those. pdf.js `PageViewport.convertToViewportRectangle` handles scale and rotation from PDF user space.
**Risk.** Extractor (PDFium) and viewer (pdf.js) are different engines. Both use PDF user space, so boxes should agree; M1 adds a test that renders highlight rects and checks they overlap pdf.js text-layer spans for the same text (target ≥ 95 % IoU match on sample PDFs).
**Replacement.** PDFium-WASM viewer if coordinate disagreement shows up.

---

## D3. Retrieval baseline components

| Component | Choice for M1 | Why | M2 will compare |
|---|---|---|---|
| Lexical | Postgres FTS (`tsvector`, GIN, `ts_rank_cd`) | Already in Postgres; no new service. Not true BM25. | `rank-bm25` 0.2.2 in-process; VectorChord-bm25 (check licence). ParadeDB `pg_search` is AGPL → excluded. |
| Dense | pgvector (`vector(640)`, HNSW cosine) | Brief requires no separate vector DB. pgvector HNSW caps `vector` at 2000 dims. | — |
| Embeddings | **Local** `microsoft/harrier-oss-v1-270m` (owner decision 2026-11-25: local, lightweight, best retrieval) | See D3a. Document text never leaves the machine for indexing. | `granite-embedding-small-english-r2` (light fallback), `gemini-embedding-2` (API option) |
| Fusion | Reciprocal rank fusion, k=60 | Parameter-light, standard. | weighted fusion |
| Reranker | none in M1 | Must earn its place. | Local ONNX cross-encoder via fastembed vs `gemini-3.5-flash-lite` listwise rerank |

### D3a. Local embedding model

Requirement (owner): local, lightweight, best retrieval available now. Permissive licence (owner may sell later). Must run on an 8 GB M2.

Candidates, scores **self-reported on model cards** (read 2026-11-25), not measured by us:

| Model | Params | Dim | Max tokens | Licence | Published score |
|---|---|---|---|---|---|
| **microsoft/harrier-oss-v1-270m** | 268M | 640 | 32,768 | MIT | MTEB v2 (multilingual) 66.5 |
| microsoft/harrier-oss-v1-0.6b | 596M | 1024 | 32,768 | MIT | MTEB v2 (multilingual) 69.0 |
| google/embeddinggemma-2 | 740M total (270M text) | 768 | 8,192 | Apache-2.0 | MTEB multilingual v2 61.36, eng v2 68.46 |
| Qwen/Qwen3-Embedding-0.6B | 596M | 1024 | 32K | Apache-2.0 | Qwen card's own tables (not used to rank here) |
| ibm-granite/granite-embedding-small-english-r2 | 47M | 384 | 8K | Apache-2.0 | MTEB v2 41-task 61.1; BEIR(15) 50.9; MTEB-v2 retrieval 53.9 |
| ibm-granite/granite-embedding-english-r2 | 149M | 768 | 8K | Apache-2.0 | MTEB v2 41-task 62.8; BEIR(15) 53.1 |
| BAAI/bge-small-en-v1.5 | 33M | 384 | 512 | MIT | MTEB-v2 retrieval 53.9 (per granite card) |

Excluded: `jina-embeddings-v5-*` (CC-BY-NC, non-commercial); `google/embeddinggemma-300m` (gated, Gemma terms; superseded by embeddinggemma-2); `MongoDB/voyage-4-nano` (needs `trust_remote_code`).

**Selection: `harrier-oss-v1-270m`.** Highest published aggregate score in the sub-300M class, 32K context (whole sections fit), MIT, loads with plain `sentence-transformers` (no remote code). Queries use its retrieval instruction (`prompt_name="web_search_query"` or a custom `Instruct: … \nQuery: `); documents get no prefix.
**Measured in M1** (`scripts/research/bench_embedder.py`, Attention paper, 48 chunks of ≤350 tokens, M2 8 GB):

| Device / dtype | Throughput | Peak RSS | Top hit for "How many attention heads…" |
|---|---|---|---|
| MPS fp16 | 5.9 chunks/s | 829 MB | **wrong** (copyright notice) |
| MPS fp32 | 3.7 chunks/s | — | correct (3.2.2 Multi-Head Attention) |
| **MPS bf16 (selected)** | **9.0 chunks/s** | **879 MB** | correct |
| CPU fp32 (4 threads) | 0.6 chunks/s | 819 MB | correct |

fp16 is unsafe for this model; GPU paths use bf16. CPU is ~15× slower: Docker (CPU) mode is usable for small documents only — M2 should test `granite-embedding-small-english-r2` as the CPU option. Model download: 536 MB.
**Caveats.** MTEB v2 score is an aggregate across tasks and languages, not English retrieval alone; self-reported. Not yet measured on this machine (owner skipped the 2 GB local bench at M0).
**Gate (M1/M2).** M1 measures throughput and peak RAM on the sample PDFs. M2 compares harrier-270m vs granite-small-r2 vs harrier-0.6b on the owner's eval set (recall@k, MRR). Keep the smallest that meets targets.
**Interface.** `Embedder` protocol in `backend/indexing/embeddings/` (local `SentenceTransformerEmbedder`, optional `GeminiEmbedder`). Model ID, dim, device, batch size from env. Changing model = re-index job keyed by `embedding_model` column on `chunks`.

Sources: <https://huggingface.co/microsoft/harrier-oss-v1-270m> · <https://huggingface.co/ibm-granite/granite-embedding-small-english-r2> · <https://huggingface.co/google/embeddinggemma-2> · <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B>

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
| Embeddings | local, see D3a (`gemini-embedding-2` kept as optional `GeminiEmbedder`) | — | — |

Owner asked for "3.8-flash-lite": **no such text model exists** (only `gemini-3.8-flash-lite-tts`, a speech model). Newest stable Flash-Lite is `gemini-3.5-flash-lite`. Swap via env when Google ships one.

**Billing (owner has Google AI Pro).** Google's docs state AI Pro subscription plans are separate from Gemini API usage tiers; the API needs a key on a Cloud Billing paid tier (prepay minimum $10). A key without billing runs on the free tier, where content may be used to improve Google's products. Source: <https://ai.google.dev/gemini-api/docs/google-ai-plans>, <https://ai.google.dev/gemini-api/docs/billing>.

**Cost policy (owner, 2026-11-25):** no cost cap for now. Token and cost accounting per request stays on.

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

---

## D7. Reasoning (thinking) controls — added post-M1

Verified from the installed `google-genai` 3.6.1 source: `types.ThinkingConfig(include_thoughts, thinking_budget, thinking_level)`;
`types.ThinkingLevel` = `MINIMAL, LOW, MEDIUM, HIGH, XHIGH`; response parts carry `thought: bool`, and
`GenerateContentResponse.text` excludes thought parts (so we iterate parts). `types.Model.thinking` (bool) and
`input_token_limit` come from `models.get` without generating.

Live (2026-11-25): `gemini-3.5-flash-lite` → `thinking: true`, MEDIUM returns thought summaries alongside structured
JSON. **Not verified:** which levels each model accepts (owner declined a probe sweep). Design: levels come from
`LLM_THINKING_LEVELS`; a 400 from the API is reported to the user as `unsupported_option` naming the model.
Thought summaries are model output about the document — stored and shown as reasoning, never used as evidence and
never logged.

---

## D8. TXT / Markdown (M3) — added 2026-11-26

**Problem.** Turn plain text and Markdown into IR blocks whose locations are exact, and show them so a citation
lands on the right characters.

**Block structure for Markdown.** Options: a hand-written line scanner; `markdown-it-py`; `mistune`.
- `markdown-it-py` 4.3.0 (MIT, dependency `mdurl` MIT; licence read from installed package metadata). It is a
  CommonMark parser, and every block token carries `token.map = [first_line, end_line)`, the source line range it
  came from. Probed on 2026-11-26 (headings ATX + setext, tight lists with continuation lines, block quotes,
  fenced + indented code, GFM tables via `.enable("table")`, HTML blocks): every map was correct. Two quirks,
  both handled: YAML front matter parses as a rule + setext heading (we blank those lines before parsing, which
  keeps line numbers), and list-item maps include a trailing blank line (we trim whitespace from each span).
- It was already in `uv.lock` (via `rich` ← `transformers`, only under the `ml` extra), so declaring it as a
  direct dependency added no download. Selected.
- Not chosen: a hand-written scanner (re-implements CommonMark edge cases); `mistune` (needs a new download and
  does not give source line maps for blocks).

**Two views (owner request 2026-11-26: "Preview | Markdown" toggle, Preview by default).**
- *Markdown* (source): line numbers, cosmetic styling; a citation is a plain character range, exact to the character.
- *Preview* (rendered): `markdown-it` 15.0.3 (MIT; deps linkify-it, mdurl, uc.micro, punycode.js MIT, entities
  BSD-2-Clause, argparse Python-2.0 used only by its CLI; ~100 KB, licences read from installed package.json).
  It is the JS original of markdown-it-py, so `token.map` line ranges match the backend's. Each rendered block
  carries `data-ls`/`data-le`; a citation washes the innermost blocks overlapping its lines and paints the exact
  quote with the CSS Custom Highlight API (words matched in order, so Markdown markers in the quote don't matter;
  block wash only when the words aren't contiguous, e.g. a quote spanning a link URL). Untrusted input: raw HTML
  escaped (`html: false`), images never fetched (alt text shown), only http(s)/mailto links kept (new tab,
  `noopener noreferrer nofollow`). Not chosen: `marked` (no block source maps), `react-markdown`/remark (larger,
  position data per node but a different parser from the backend).

**Encoding.** No `charset-normalizer` (guessing would let the browser and backend disagree). Rule: BOM
(UTF-8/UTF-16) → strict UTF-8 → strict Windows-1252 → reject. Python's strict `cp1252` rejects the five bytes
WHATWG maps to C1 controls, so every accepted file decodes to the same string in `TextDecoder`. The same five
fixtures are tested on both sides (`test_text_extraction.py::test_decode`, `text.test.tsx`).

**Offsets.** Backend offsets are code points (Python `str`). The viewer converts code point → UTF-16 index once
per document (identity when there are no astral characters). Tested with emoji in both test suites.

**Large text.** Lines render in groups of 200; groups off screen are fixed-height placeholders until an
`IntersectionObserver` sees them (no virtualisation dependency). Limit `MAX_TEXT_CHARS` = 2,000,000.
Not measured yet on a 2M-character file.
