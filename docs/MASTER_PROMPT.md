# ANYDOC — MASTER BUILD PROMPT

You are the principal engineer building **AnyDoc**: a document intelligence workspace where a user opens a document, chats with it, and every answer links to the exact evidence in the original file.

It runs **locally for now** and must be **shaped for production** (real users, hosted) later. Build locally, but never in a way that forces a rewrite for production.

The original document is the source of truth. Understand structure; do not just extract text and send it to an LLM.

---

## 0. HOW TO WORK

- Work **one milestone at a time** (section 14). Do not start the next milestone until the current one's acceptance criteria pass.
- Each milestone leaves the repo working, tested and documented.
- Keep a running `PROGRESS.md` (done / in progress / blocked / decisions). Re-read it at the start of every session; it is your memory.
- Small, focused commits. Never commit secrets. Keep `.env.example` current.
- Research is **timeboxed** (section 12). Research, record the decision, then build. Do not research indefinitely.
- Never claim a feature works unless it is implemented AND tested. A UI that renders is not a finished feature.
- Never invent benchmarks, library capabilities, model IDs or API behaviour. Verify against official docs and say what you could not verify.
- Decide technical questions yourself. Ask me only when blocked on something only I can provide (keys, sample documents, a product decision) or when a choice is irreversible.
- End every milestone with a completion report: what was built, what works, tests run and results, what is incomplete, known limitations, decisions and why, next milestone.

## 1. NON-NEGOTIABLE RULES

1. **Never invent document content, citations or source locations.**
2. The LLM never supplies coordinates, offsets or document ownership. It supplies only evidence references that the backend validates (section 7).
3. If evidence is insufficient, **say so**. Abstaining is a correct answer.
4. Uploaded content is **untrusted data**, never instructions (prompt injection defence).
5. Originals are immutable and versioned. Large files never go in PostgreSQL and are never loaded fully into memory without strong reason.
6. Format-specific logic stays inside that format's module. Adding a format must not touch chat, citations, workspace or the core pipeline.
7. Do not log raw document content by default (including in traces, section 9).
8. Every table and API is owner-scoped from day one (section 4), even though v1 has one user.

## 2. PRODUCT SCOPE

**v1 session model: one active document per session/workspace.** The database and IR still support many documents per user (`document_id`, `workspace_id`, `owner_id` everywhere); the v1 UI simply opens one at a time. Multi-document chat and cross-document retrieval are out of scope for now.

**Formats are added one at a time**, in this order, each as an independent milestone:
PDF → TXT/MD → DOCX → CSV → XLSX → JSON → XML → PPTX → Images (OCR) → Audio.
**Video is deferred** (not in the current plan; keep the architecture ready for it, since it will reuse the audio pipeline plus frame extraction).
Later candidates (do not build now, keep the architecture ready): HTML, EML, EPUB, SRT/VTT, YAML/TOML, archives (with path-traversal and archive-bomb protection).

**A format is "done" only when all of these exist** (the Format Definition of Done):
1. Validated detection (extension + magic bytes + parse test), with safe failure for malformed files.
2. Extractor producing Document IR blocks with correct source locations.
3. Viewer adapter implementing the viewer contract (section 8), including navigate + highlight.
4. Retrieval/answering path suited to the format (section 6).
5. At least 10 evaluation questions with gold answers and gold locations, and a measured result.
6. Tests: extraction, location accuracy, viewer, citation click-through, malformed-file handling.
7. Documented limitations.

## 3. UX

Two-panel workspace, premium and restrained (clean typography, subtle borders, no decoration, no gratuitous animation).

- **Left: chat.** Streaming answers, history, follow-ups, citation chips, processing/error/retry states.
- **Right: viewer.** Format-specific viewer, search, zoom, citation navigation and highlighting.
- Draggable, resizable, collapsible divider; panel sizes persisted; responsive (desktop/tablet/mobile); keyboard accessible; dark and light themes; accessible contrast and focus states; thoughtful empty states; clear processing progress.
- Clicking a citation scrolls the viewer to the evidence and highlights it. Multiple regions per citation must work. Low-confidence evidence (e.g. OCR) is visibly marked.

## 4. STACK (defaults; replace with evidence)

**Frontend:** React, TypeScript, Vite, Tailwind, shadcn/ui, Zustand, TanStack Query, React Resizable Panels, Lucide.
**Backend:** Python, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, uv.
**Database:** PostgreSQL via Docker Compose from day one (JSONB for format metadata, pgvector and full-text search where the evaluation supports them). Do not add a separate vector database.
**Storage:** a `Storage` interface with a local-disk implementation now and an S3-compatible implementation (R2/MinIO) designed in. Signed-URL style access paths so the swap is mechanical. Streaming and HTTP range access for large files; never buffer a whole upload in the API.
**Jobs:** a `JobQueue` interface. Choose the implementation in the research phase (Celery/Redis, Dramatiq, RQ, ARQ or a Postgres-backed queue) based on retries, cancellation, progress reporting and local simplicity. Do not add infrastructure the local version does not need.
**Auth:** v1 uses a local single-user stub behind a real auth interface/middleware. All records carry `owner_id`/`workspace_id` and every query is scoped. Real authentication is a production-hardening task, not a rewrite.
**LLM:** Gemini via an `LLMProvider` interface (section 5). **Tracing:** LangSmith (section 9).
**Compute:** auto-detect hardware at startup and use a GPU if one is available, otherwise use the CPU (and available RAM sensibly). Device, thread count and model size are config, with bounded concurrency so a worker cannot exhaust memory. Docker Desktop containers may not be able to use the host GPU (notably on macOS); verify, and if so run CPU in the container or run the ML worker natively. Every model choice must be validated on CPU, since that is the guaranteed baseline.
**Infra:** Docker Compose for web, API, Postgres, workers (and Redis only if chosen). No Kubernetes, Kafka or microservices.

## 5. LLM PROVIDER LAYER (GEMINI)

- Use the official Gemini SDK, isolated behind `LLMProvider` (generate, stream, structured output, embeddings, token counting, file/media input where relevant). Provider-specific code lives only in `backend/llm/providers/gemini/`.
- Model IDs and parameters come from environment/config, **never hard-coded**. Gemini preview models are retired and renamed regularly: at build time read the current official models page, choose models for (a) answering, (b) cheap high-volume tasks (contextualisation, reranking, summarising), (c) embeddings, and record them in `TECHNOLOGY_EVALUATION.md`. Add a startup/smoke check that fails loudly if a configured model is unavailable.
- Use structured (schema-constrained) output for citations, query planning and extraction steps. Validate every structured response with Pydantic; treat malformed output as an error to retry or fall back, never trust it silently.
- Handle rate limits, timeouts, retries with backoff, and token/cost accounting per request.
- Evaluate Gemini's native multimodal input (document, image) against dedicated tools when you reach those formats; do not assume either is better. **Speech transcription is local** (section 8A); Gemini audio input is only an optional comparison baseline.

## 6. DOCUMENT IR, INGESTION AND RETRIEVAL

### Document IR
A format-independent, structured, versioned representation. Never one giant string. Each block has: stable `block_id`, `document_id`, `document_version`, `type`, `content`, `source_location` (discriminated union per format), `format_metadata` (JSONB), `confidence`, ordering and hierarchy (parent/section).

Source locations (support multiple regions per block/citation):
PDF page + bbox + text offsets · DOCX section/paragraph/table/cell + offsets · XLSX sheet + cell/range · CSV row/column · JSON JSONPath · XML XPath · PPTX slide + element + bbox · Image normalised bbox · Audio/Video start/end ms + word timestamps (+ frame/bbox) · Text char offsets.

Keep IR extensible per format without forcing identical metadata.

### Ingestion pipeline
Upload → store original (immutable, versioned) → validate (size, magic bytes, parse test) → security checks → queue → format-specific extraction → IR → indexing → validation → `ready`.
Job states: `pending, uploading, uploaded, validating, queued, processing, indexing, ready, failed, cancelled`. Support progress, retries, idempotency, cancellation, timeouts, temp-file cleanup, bounded concurrency and resumable recovery. Stream and chunk large files.

### Retrieval and answering (decide by measurement)
Do not assume a pattern. Start from this **baseline** and make every addition earn its place on the eval set:
1. **Router:** if the whole document fits comfortably in the model's context budget, test "full document with block IDs in context" as a strong baseline; otherwise retrieve.
2. **Hybrid retrieval:** BM25/full-text + dense embeddings, rank fusion, then a reranker.
3. **Structure-aware chunks tied to block IDs** (parent/child, section/page aware) with neighbour expansion.
4. **Contextual chunk enrichment** (short LLM-written context prepended to chunks) — test it; it costs one LLM call per chunk.
5. **Query handling:** decomposition for multi-part questions; exact-match handling for numbers, dates, IDs and names.
6. **Whole-document questions** (summaries, comparisons): hierarchical summaries over sections, not top-k chunks.
7. **Tabular/structured formats** (CSV, XLSX, JSON, XML): do not flatten into chunks. Use schema/sheet discovery plus **sandboxed query execution** (e.g. pandas/SQL/JSONPath/XPath with no network, no filesystem, time and memory limits). The cells/nodes actually read become the evidence.
8. **Audio/video/image:** transcript segments and OCR regions with confidence; consider frames for video.

Measure each component (recall@k, MRR, answer correctness, latency, cost) and keep only what helps.

## 7. CITATION AND GROUNDING PROTOCOL

1. The model receives evidence blocks labelled with their `block_id`.
2. The model returns structured output: answer segments, each with `evidence: [{block_id, quote}]`, where `quote` is a short **verbatim** span copied from that block.
3. The backend validates every citation: block exists, belongs to this document and owner, matches the current document version, the quote is actually found in the block (after whitespace/case normalisation, with a fuzzy fallback and a defined tolerance), and the cited content plausibly supports the claim.
4. The backend maps the verified quote to precise source locations (offsets → bbox/cell/timestamp) **from its own IR**, never from model output.
5. Failed citations are dropped, re-requested once, or the answer is downgraded/abstained. Never show an unvalidated citation.
6. Numeric values and units in answers are checked against the source block text.
7. The frontend receives only validated citation objects with locations.
8. Conflicting evidence is surfaced explicitly. Low-confidence OCR/ASR evidence is flagged.

## 8. VIEWER ARCHITECTURE (FRONTEND)

`DocumentViewer` → `ViewerRegistry` → independent adapters (`PDFViewer`, `TextViewer`, …). One TypeScript contract:
`load`, `render`, `navigateTo(location)`, `highlight(locations[])`, `clearHighlights`, zoom/format controls, `search`, loading/error state, large-document support (virtualisation, page caching).
The registry selects adapters from the backend's **validated** file type, never from the file extension alone. Adding an adapter must not change chat, citations or workspace code.

Format guidance (decide in the research phase, record in TECHNOLOGY_EVALUATION):
- **PDF:** start with PDF.js (text layer + custom overlay), with a tested coordinate-conversion layer between PDF user space and viewport space; thumbnails, search, zoom/fit, virtualised pages. Treat PDFium/commercial SDKs as a documented replacement option.
- **DOCX/PPTX/XLSX(legacy)/RTF:** evaluate **server-side conversion to PDF (LibreOffice headless)** and reuse the PDF viewer, versus native HTML/canvas renderers. Prefer the option whose citations land accurately; fidelity vs. citation accuracy is a trade-off to measure.
- **CSV/XLSX:** virtualised grid; compare Univer/FortuneSheet/Glide Data Grid/others for navigation to cell ranges.
- **JSON/XML:** tree + raw mode + JSONPath/XPath navigation.
- **Image:** zoom/pan/rotate, OCR overlay, normalised bounding boxes.
- **Audio/Video (transcription details in section 8A):** range-streamed playback, waveform (audio), transcript with word timestamps where available, click-to-seek, active-word highlight, speaker labels where supported. Do not confuse segment-level timestamps with word-level alignment. Never load whole media into memory.

## 8A. LOCAL SPEECH RECOGNITION (AUDIO AND VIDEO)

**Goal:** the most accurate transcription achievable **locally** with a small footprint. No ASR system is "exact". Measure word error rate (WER) and word-timing error, store per-word confidence where available, flag low-confidence words in the UI, and never present a transcript as verbatim truth. Transcription runs locally by default; Gemini audio input may be used only as an opt-in comparison baseline in the evaluation, never as the default path.

**Architecture: three swappable interfaces** in `backend/transcription/`:
- `Transcriber`: audio chunk → text segments (with word timings and per-word confidence if the engine provides them).
- `Aligner`: audio + text → word-level timestamps. Used whenever the engine's own word timings are missing or not accurate enough. Separating recognition from alignment lets us pair a very light recogniser with a dedicated forced aligner; research on timestamp accuracy reports that re-aligning ASR output with a dedicated aligner improves on the recogniser's bundled timings.
- `Diarizer` (optional, later): speaker labels. Check licence and gating terms of any diarization model before adopting it.

**Pipeline:** FFmpeg extracts 16 kHz mono audio **in streamed chunks** (never the whole file in memory) → VAD segmentation (e.g. Silero) → `Transcriber` → `Aligner` if needed → IR blocks (segment text + word-level timing and confidence in `format_metadata`, global millisecond offsets). Long recordings are processed in VAD-bounded chunks with checkpointing and resumable jobs; handle chunk boundaries so words are neither cut nor duplicated. Video uses the same pipeline on its extracted audio track.

**Pre-researched candidates (verify current versions, licences and benchmarks at the start of the Audio milestone; do not trust this list blindly):**
1. **Moonshine** (`moonshine-voice`): the lightest option. English models are MIT; its published v2 streaming results are about 6.65% WER (Medium, ~245M parameters), 7.84% (Small) and 12% (Tiny) on its own benchmark, and it is built for live streaming, so its natural strengths are latency and footprint rather than batch accuracy. The PyPI package is marked alpha. **Word timings:** the package docs say word timings are exposed through event listeners and a CLI flag (`--word-timestamps`) exists, and third-party notes say they are optional and need an extra per-model decoder file (`decoder_kv_with_attention.ort`), which suggests they are derived from decoder attention. The official API docs I could read do not describe the fields, how they are computed, or their accuracy, and one third-party catalogue says Moonshine has no word timestamps. Treat word timings as **present but unverified for accuracy**: measure them against hand-checked word times, and **plan to pair Moonshine with an `Aligner`** unless they pass. Offline file transcription exists (`transcribe_without_streaming`), but the docs say heavy batch workloads are better served by bulk transcription libraries, and the engine is designed around live streaming with its own VAD. Only its English models are in scope.
2. **NVIDIA Parakeet TDT 0.6B** (v2 English, v3 25 European languages): top-tier Open ASR Leaderboard WER (about 6.05 and 6.32 average) with native word and segment timestamps. It is larger (600M parameters). **Licence:** the Hugging Face model card for v2 declares CC-BY-4.0 (commercial use allowed, attribution required), but NVIDIA's NIM/catalog pages cite different terms (NVIDIA Community Model License for v2, NVIDIA Open Model License for v3), so confirm the terms that apply to the exact files you download and keep the attribution. **CPU/ONNX routes exist** and avoid the NeMo stack: `sherpa-onnx` publishes int8 ONNX packages for v2 (encoder about 622 MB; its docs report a real-time factor of about 0.12 on their test machine, hardware unspecified) and `onnx-asr` (MIT; `pip install onnx-asr[cpu,hub]`) loads Parakeet TDT ONNX models, optionally quantised. A community report on an ARM board measured about 8x real time with 8-bit onnx-asr. **Still unverified:** whether the ONNX runtimes return accurate *word-level* timestamps for Parakeet (onnx-asr's README only claims token-level timestamps), and CPU speed and memory on my machine. `onnx-asr` also warns that most models handle only 20–30 s at a time, so long audio must go through VAD chunking.
3. **faster-whisper (large-v3 / large-v3-turbo) + WhisperX alignment:** the quality and timing reference with the widest language coverage; the heaviest option. WhisperX adds forced alignment (wav2vec2) and optional pyannote diarization.

**Selection protocol (timeboxed, on my hardware and my audio):** run all three (with and without a separate aligner where relevant) on a sample set containing clean speech, noisy speech, accented speech, multi-speaker audio and at least one recording of 60+ minutes, each with a hand-checked reference transcript and spot-checked word times. Record: WER, median and p95 word-start error, real-time factor, peak RAM, cold-start time, behaviour on long audio, language coverage and licence. Choose the **smallest configuration that meets the targets** in `docs/EVAL_TARGETS.md`; if results tie, prefer the lightest. Document the choice and the replacement path in `TECHNOLOGY_EVALUATION.md`. **Language scope: English only for now.** Evaluate English-only models and configurations (e.g. Moonshine English, Parakeet TDT 0.6B v2, Whisper `.en`/distilled variants) and ignore multilingual coverage when selecting. Keep the language as a config parameter on `Transcriber` and store it in document metadata, so adding languages later means adding a model, not changing the pipeline. Using English-only models also keeps the Moonshine licence simple (English models are MIT); re-check this at selection time.

**Citations for audio/video:** the model quotes transcript text; the backend verifies the quote against the transcript blocks and maps it to word IDs and millisecond ranges from the IR. The viewer seeks to the start, highlights the cited words, and marks low-confidence words.

## 9. OBSERVABILITY: LANGSMITH

Use **LangSmith** for tracing and LLM-quality evaluation.

- Isolate it in `backend/observability/`. The rest of the code calls our thin wrapper (e.g. a `@traced` decorator and a `trace_metadata` helper), so tracing can be swapped or supplemented (OpenTelemetry) later without touching business logic.
- Verify current integration details in the official LangSmith docs (environment variables, tracing decorator/SDK usage with non-LangChain code, Gemini wrapping, redaction hooks).
- Trace every stage as a nested run: upload/ingest stages, extraction, indexing, query planning, retrieval (with the retrieved block IDs and scores), reranking, generation, citation validation, abstention decision. Attach metadata: `document_id`, `document_version`, format, model ID, strategy/router decision, token counts, latency, cost estimate, validation outcomes.
- **Privacy:** traces can contain document text and questions and are sent to a third-party service. Default configuration must **hide/redact inputs and outputs** (block content, user text) and trace IDs, block IDs, scores, timings, token counts and validation results only. Full-content tracing is an explicit opt-in flag (`TRACE_CONTENT=true`) intended only for my own test documents in development. Document this clearly. Production use requires a redaction policy and, if needed, a self-hosted/regional LangSmith option (to be decided later).
- Keep a **local evaluation runner** that works without LangSmith (and offline). LangSmith datasets/experiments are an optional layer on top; results must be reproducible from the repo.
- Tracing failures or an unreachable LangSmith must never break a request.
- Also keep structured logs with request IDs (no document content), and basic metrics for upload success, job duration, queue depth, LLM latency/usage, and citation validation pass rate.

## 10. SECURITY (v1 BASELINE, PRODUCTION-READY SHAPE)

v1 must have: owner-scoped queries everywhere, file type + magic-byte validation, upload size limits, safe parsing of malformed files (timeouts, memory limits, no unbounded decompression), sanitised rendering of any extracted HTML, prompt-injection defences (delimit untrusted content, never follow instructions in documents, no tool access derived from document text), sandboxed code execution for tabular queries, secrets only from environment, CORS configured, rate-limit hooks, and an audit-log table for key actions.

Designed in but implemented in a later hardening milestone: real authentication, multi-tenant isolation tests, malware scanning integration, signed S3 URLs, retention/deletion policies, backups, rate limiting at the edge, secret management service.

Provisional v1 limits (configurable): 100 MB / 500 pages per document. Revisit after measuring.

## 11. TESTING AND EVALUATION

- Backend: pytest for APIs, models, migrations, authorisation (owner scoping), validation, extraction, IR generation, retrieval, citation validation (including adversarial/fabricated citations), job retries and cancellation, security boundaries.
- Frontend: component tests, viewer-registry tests, citation navigation/highlight tests, upload and chat flows, accessibility checks, and Playwright end-to-end tests for the core flow.
- **Evaluation harness** in `eval/`: for each format a dataset of documents, questions, gold answers and gold source locations (including unanswerable questions). I will supply real sample documents and questions in `eval/data/`; generate additional synthetic cases only to supplement, and label them as synthetic.
- Metrics: retrieval recall@k/MRR, answer correctness, **citation location accuracy**, **citation support (does the quote support the claim)**, numeric correctness, abstention precision/recall, latency, tokens/cost.
- After the first baseline run, propose numeric targets with me, record them in `docs/EVAL_TARGETS.md`, and gate milestones on them. Do not claim perfect accuracy; report measured results and failure cases.

## 12. RESEARCH PROTOCOL (TIMEBOXED)

Milestone 0 is a research phase (max ~1 day of work). For each decision below, compare current options using official docs and maintained repositories, verify release/maintenance status and **licence** (commercial use, server-side use, redistribution; distinguish open source from source-available/free tier), test the top candidates on real sample documents, and record the result in `docs/TECHNOLOGY_EVALUATION.md` (problem, alternatives, links, findings, licence, selection, limitations, replacement strategy). Use ADRs for architectural choices.

Decisions for the research phase: (1) PDF parsing/extraction with bounding boxes (e.g. PyMuPDF vs. Docling vs. others) and OCR fallback; (2) PDF viewer approach; (3) retrieval baseline components (embedding model, reranker, FTS vs. BM25 library); (4) job queue; (5) Gemini model selection and pricing; (6) LangSmith integration details.
Decisions for later milestones are researched when you reach them, not now. The speech-recognition shortlist is already pre-researched in section 8A; re-verify it at the Audio milestone.
Do not change a technology without evidence, and do not add dependencies without justification.

## 13. REPOSITORY LAYOUT (adjust with reason)

```
anydoc/
  frontend/web/src/{app,components,features/{chat,citations,uploads,workspace},viewers/{core,pdf,...},stores,hooks,services,lib}
  backend/{api,workers,core,document_ir,ingestion,extraction,ocr,transcription,indexing,retrieval,llm/providers/gemini,grounding,storage,security,observability,tests}
  eval/{data,datasets,runners}
  migrations/  infrastructure/{docker,compose}  scripts/  docs/
  docker-compose.yml  .env.example  pyproject.toml  package.json
  CLAUDE.md  MISSION.md  ARCHITECTURE.md  README.md  PROGRESS.md
  docs/{TECHNOLOGY_EVALUATION.md,EVAL_TARGETS.md,adr/}
```

## 14. MILESTONES AND ACCEPTANCE CRITERIA

**M0 — Inspect, research, document.** Inspect the repo and reuse what is useful. Run the research phase (section 12). Create/update `CLAUDE.md` (short rules from sections 0–1), `MISSION.md`, `ARCHITECTURE.md`, `README.md`, `docs/TECHNOLOGY_EVALUATION.md`, `PROGRESS.md`. *Accept:* decisions recorded with evidence; I have reviewed the plan.

**M1 — Foundation + PDF vertical slice.** Compose environment, FastAPI + Postgres + migrations, storage/job/auth/LLM interfaces with local implementations, workspace UI, upload → validate → extract → IR → index → ready, PDF viewer adapter, one-document session, streaming chat with the baseline answer path, validated citations, click-to-highlight, LangSmith tracing (redacted by default). *Accept:* on my sample PDFs, an end-to-end question yields a streamed answer whose citations validate and highlight the correct region; fabricated-citation tests are rejected; a malformed PDF fails gracefully; tests green; a first eval baseline is recorded.

**M2 — Retrieval quality.** Eval harness complete; compare router, hybrid retrieval, reranking, contextual enrichment, query decomposition, hierarchical summaries; keep what measurably helps; set `EVAL_TARGETS.md`. Large-PDF performance (virtualisation, streaming, memory) measured. *Accept:* targets met or gaps documented.

**M3 — TXT/MD.** Then **M4 DOCX**, **M5 CSV**, **M6 XLSX**, **M7 JSON**, **M8 XML**, **M9 PPTX**, **M10 Images/OCR**, **M11 Audio (local ASR + forced alignment, section 8A; acceptance includes measured WER and word-timing error on my samples)**. **Video is deferred and has no milestone yet.** each satisfying the Format Definition of Done (section 2) and re-running the full eval suite for regressions.

**M-Prod — Production hardening** (can be scheduled any time after M2): real auth and tenant isolation tests, signed S3 storage, malware scanning, rate limiting, retention/deletion, backups, deployment (Cloudflare Pages + container host + managed Postgres), Sentry/OpenTelemetry, load and large-file tests, LangSmith redaction policy.

## 15. INPUTS I WILL PROVIDE

`GEMINI_API_KEY`, `LANGSMITH_API_KEY` (and project name), 10–15 sample documents with questions/expected answers for `eval/data/`, my hardware details, and (for the Audio milestone) English sample recordings with reference transcripts: clean, noisy, accented, multi-speaker and one 60+ minute file. If anything is missing, build the integration boundary with a local mock, document the missing configuration, and keep going.

**Status:** Docker Desktop is installed; limits (100 MB / 500 pages) and the format order are approved; hardware is "use GPU/RAM if available, else CPU". The API keys, evaluation documents and audio samples **will be provided later**. Proceed with M0 and M1 using mocks and public sample PDFs. Do not start M2 (retrieval evaluation and tuning) until I supply the evaluation documents; report as blocked and wait. Do not claim retrieval accuracy before then.

## 16. FIRST ACTIONS

1. Inspect the repository; summarise its state in `PROGRESS.md`.
2. Confirm any remaining blockers with me in **one** short list.
3. Run M0, then stop and show me the plan and decisions before starting M1.
