# Architecture

Status: **M0 plan, awaiting review.** Nothing below is implemented yet. Technology choices and their evidence: `docs/TECHNOLOGY_EVALUATION.md`. Architectural decisions: `docs/adr/`.

## 1. System overview

```
 Browser (React SPA)
  ├─ Chat panel ── SSE stream ─────────────┐
  └─ Viewer panel ── HTTP range GET ───┐   │
                                       ▼   ▼
                         FastAPI (api)  ── AuthProvider → Principal(owner_id, workspace_id)
                          │   │   │
               Storage ◄──┘   │   └──► Answer engine ─► Retriever ─► Postgres (FTS + pgvector)
          (local disk / S3)   │                     └─► LLMProvider (Gemini) ─► Grounder (validate)
                              ▼
                    JobQueue (procrastinate, in Postgres)
                              │
                         Worker(s) ─► FormatRegistry ─► extractor ─► Document IR ─► Indexer
                              │
                     Observability wrapper (@traced → LangSmith, redacted) + structured logs
```

Processes: `web` (Vite dev / static build), `api` (FastAPI, uvicorn), `worker` (procrastinate worker), `postgres` (pgvector image). No Redis: the queue lives in Postgres (ADR-0003).

## 2. Repository layout

```
frontend/web/src/
  app/            routes, providers, theme
  components/ui/  shadcn primitives restyled with DESIGN.md tokens
  features/       chat, citations, uploads, workspace
  viewers/core/   ViewerContract, ViewerRegistry, DocumentViewer
  viewers/pdf/    PDF adapter (pdf.js)
  stores/ hooks/ services/ lib/
backend/
  api/            routers, SSE, error mapping, dependencies
  core/           config (pydantic-settings), db session, principal, errors, ids
  security/       auth interface + local stub, upload validation, rate-limit hooks, audit log
  storage/        Storage protocol, LocalDiskStorage, (S3Storage later)
  workers/        JobQueue protocol, procrastinate impl, task definitions
  ingestion/      pipeline orchestration, state machine
  document_ir/    IR models, SourceLocation union, text normaliser + offset maps
  extraction/     FormatHandler protocol, registry, formats/pdf/ ...
  ocr/ transcription/   (later milestones; interfaces only)
  indexing/       chunker, embeddings, FTS
  retrieval/      router, hybrid search, fusion, neighbour expansion
  llm/            LLMProvider protocol, prompts, schemas; providers/gemini/
  grounding/      citation validation, quote→location mapping, numeric checks
  observability/  @traced, trace_metadata, redaction, logging, metrics
  tests/
eval/{data,datasets,runners}   migrations/   infrastructure/{docker,compose}   scripts/   docs/
```

## 3. Core interfaces (backend)

All are `typing.Protocol`s with a local implementation now and a production one designed in.

| Interface | Local (v1) | Production | Key methods |
|---|---|---|---|
| `Storage` | `LocalDiskStorage` (content-addressed under `DATA_DIR`) | `S3Storage` (R2/MinIO) | `put_stream`, `open_range`, `stat`, `delete`, `access_url(key, ttl)` |
| `JobQueue` | procrastinate on Postgres | same, separate DB or host | `enqueue(name, payload, idempotency_key)`, `cancel(job_id, abort)`, `progress(job_id)` |
| `AuthProvider` | `LocalSingleUserAuth` (fixed owner/workspace from config) | OIDC/JWT | `authenticate(request) -> Principal` |
| `LLMProvider` | `GeminiProvider`, `FakeProvider` for tests/offline | same | `generate`, `stream`, `generate_structured`, `embed`, `count_tokens` |
| `FormatHandler` | one per format | — | `detect(head_bytes, filename)`, `validate(path)`, `extract(path) -> Iterable[Block]` |
| `Tracer` | LangSmith wrapper, no-op fallback | + OpenTelemetry | `@traced(name, kind)`, `trace_metadata(**kv)` |

`Storage.access_url` returns an API path (`/api/files/{id}/content`) locally and a signed URL in production, so the frontend never cares which.

Uploads stream to storage in chunks (`UploadFile` read in 1 MiB pieces, hashed as it goes); the API never buffers a whole file. Viewer reads use HTTP `Range` (pdf.js range requests), so large PDFs load progressively.

## 4. Data model (Postgres)

Every row carries `owner_id` and `workspace_id`; every repository method takes a `Principal` and filters on both. A test suite asserts cross-owner access returns 404.

```
users(id, ...)                       workspaces(id, owner_id, name)
documents(id, owner_id, workspace_id, title, current_version, status, created_at)
document_versions(id, document_id, version, storage_key, sha256, size_bytes,
                  detected_format, mime, page_count, metadata JSONB, created_at)   -- immutable
ingestion_jobs(id, document_version_id, state, progress, attempts, error_code,
               error_detail, idempotency_key UNIQUE, queue_job_id, timestamps)
blocks(id, document_version_id, block_id TEXT, ordinal, parent_block_id, section_path TEXT[],
       type, content TEXT, source_location JSONB, format_metadata JSONB, confidence REAL)
chunks(id, document_version_id, block_ids TEXT[], text, context_prefix, tsv TSVECTOR,
       embedding VECTOR(768), token_count)                    -- GIN(tsv), HNSW(embedding)
chat_sessions(id, document_id, ...)   messages(id, session_id, role, content, status, usage JSONB)
citations(id, message_id, segment_index, block_id, quote, locations JSONB, match_score, flags TEXT[])
audit_log(id, owner_id, workspace_id, actor, action, target, at, details JSONB)
```

Job states (brief §6): `pending → uploading → uploaded → validating → queued → processing → indexing → ready`, plus `failed`, `cancelled`. Transitions are enforced in one function; illegal transitions raise.

## 5. Document IR

```python
class Block(BaseModel):
    block_id: str              # stable: f"{format}:{page or part}:{ordinal}:{hash8(content)}"
    document_id: UUID
    document_version: int
    type: Literal["heading","paragraph","list_item","table","table_cell","caption",
                  "footnote","code","transcript_segment","ocr_region", ...]
    content: str
    source_location: SourceLocation          # discriminated on `kind`
    format_metadata: dict[str, Any]          # JSONB, per-format
    confidence: float | None                 # OCR/ASR; None = native text
    ordinal: int
    parent_block_id: str | None
    section_path: list[str]
```

`SourceLocation` is a discriminated union. Each variant allows **multiple regions**.

- `PdfLocation{kind:"pdf", regions:[{page, rects:[[x0,y0,x1,y1]...]}], char_start, char_end}`
- `TextLocation{kind:"text", char_start, char_end, line_start, line_end}`
- later: `DocxLocation`, `SheetLocation{sheet, range}`, `CsvLocation{rows, cols}`, `JsonLocation{pointer/jsonpath}`, `XmlLocation{xpath}`, `SlideLocation{slide, element, rects}`, `ImageLocation{rects_normalised}`, `MediaLocation{start_ms, end_ms, word_ids}`.

**PDF coordinate convention (tested in M1):** PDF points, origin at the **top-left of the page's CropBox**, y down, **before page rotation**. The extractor converts from pdfium's bottom-left page space; the viewer converts to screen with pdf.js `viewport.convertToViewportRectangle`, which applies rotation and scale. Tests cover rotated pages (90/180/270) and non-zero CropBox origins.

Each PDF block also stores a per-character box table (in `format_metadata`, compact array) so any verified substring maps to exact rects — this is what lets the backend, not the model, produce the highlight.

## 6. Ingestion pipeline

```
POST /api/documents (stream) → Storage.put_stream (sha256) → document_versions row
  → validate: size ≤ MAX_UPLOAD_MB, magic bytes, extension agreement, parse test in subprocess
    (timeout + RLIMIT_AS), page limit ≤ MAX_PAGES
  → enqueue ingest(document_version_id)  [idempotency_key = sha256 + version]
worker: extract (FormatRegistry) → IR blocks → chunk → FTS + embeddings → validate → ready
```

- Parsing of untrusted files runs in a **child process** with CPU time and memory limits, so a hostile PDF cannot take down the worker.
- Progress is written to `ingestion_jobs.progress` and pushed to the client (SSE `GET /api/documents/{id}/events`; polling fallback).
- Cancellation uses procrastinate `cancel_job_by_id(abort=True)`; tasks check `should_abort()` between pages.
- Retries: exponential backoff for transient errors (LLM/embedding rate limits); no retry for deterministic failures (malformed file).
- Temp files live under a per-job dir removed in `finally`.

## 7. Retrieval and answering (M1 baseline; M2 measures everything)

1. **Router.** If the whole document's IR ≤ `FULL_CONTEXT_TOKEN_BUDGET` (default 120k tokens, config), send all blocks labelled by `block_id`. Otherwise retrieve.
2. **Hybrid retrieval.** Postgres FTS (`websearch_to_tsquery`, `ts_rank_cd`) + pgvector cosine (HNSW) → reciprocal rank fusion (k=60) → top-k chunks → expand to their blocks + neighbours.
3. **Exact-match boost** for numbers, dates and quoted strings in the question (FTS phrase query).
4. Reranker, contextual enrichment, query decomposition, hierarchical summaries: **not in M1**. Each is added in M2 only if it wins on the eval set.

## 8. Citation and grounding protocol

Model output schema (Gemini structured output, validated by Pydantic):

```json
{ "status": "answered" | "insufficient_evidence" | "conflicting_evidence",
  "segments": [ { "text": "...", "evidence": [ { "block_id": "pdf:3:12:ab12cd34", "quote": "verbatim span" } ] } ] }
```

Backend validation, per evidence item:
1. `block_id` exists, belongs to this document version and principal.
2. Quote found in block content: exact → normalised (NFKC, ligature fold, de-hyphenate line breaks, collapse whitespace, casefold) with an index map back to raw offsets → fuzzy fallback (`rapidfuzz` partial alignment, score ≥ `QUOTE_FUZZY_MIN`, default 90, quote ≥ 12 chars).
3. Numbers and units in the segment text must appear in at least one cited block.
4. Raw offsets → rects via the block's char-box table. Locations come only from the IR.

Outcome: invalid evidence dropped; a segment left with no valid evidence triggers one re-ask; still invalid → segment removed and the answer downgraded or abstained. The frontend receives only validated citation objects.

**Streaming.** Gemini streams the structured JSON. An incremental JSON parser emits `text_delta` events for segment text as it arrives. When a segment closes, its evidence is validated and a `citation` event is emitted (or a `segment_retracted` event if it failed). Final `done` event carries status and usage. Chips appear only once verified.

Prompt-injection defence: document text is wrapped in delimited, labelled `<document_block id=…>` elements; the system prompt states block content is data; no tools are exposed to the model in the answer path.

## 9. Frontend

- Two panels via `react-resizable-panels`: chat left, viewer right; sizes persisted (`autoSaveId`); collapse either; keyboard-resizable separator; stacked tabs on mobile.
- `ViewerContract` (TS): `load(source)`, `render(container)`, `navigateTo(location)`, `highlight(locations[])`, `clearHighlights()`, `zoom`, `search(query)`, `state: loading|ready|error`.
- `ViewerRegistry` maps the backend's **validated** `detected_format` to an adapter. Chat and citation code depend only on the contract.
- PDF adapter: `pdfjs-dist` directly (not a wrapper) for control over virtualised pages, text layer and a custom highlight overlay; range loading; thumbnails; find; fit-width/fit-page/zoom.
- State: Zustand for UI (panel layout, active citation, theme); TanStack Query for server state; SSE handled in a small `useAnswerStream` hook.
- Design system: `docs/DESIGN.md` (dark Claude-style default + light theme).

## 10. Observability

`backend/observability/` exposes `@traced(name, run_type)` and `trace_metadata(**kv)`. Internally it uses LangSmith `@traceable` with a `Client(hide_inputs=..., hide_outputs=...)` built from config. Default: inputs/outputs replaced with `{}`-style redacted payloads; metadata (IDs, scores, timings, tokens, model, validation outcomes) kept. `TRACE_CONTENT=true` opts in to full content for dev test documents. Tracing errors are swallowed and logged; an unreachable LangSmith never fails a request. The Gemini client is **not** wrapped with `langsmith.wrappers.wrap_gemini` (beta, and it would capture prompts); generation spans are emitted by our wrapper with token counts only.

Structured JSON logs with `request_id`, no document content. Metrics (counters/histograms, Prometheus format at `/metrics`): uploads, job duration, queue depth, LLM latency/tokens, citation pass rate.

## 11. Security baseline (v1)

Owner scoping everywhere · magic-byte + extension + parse-test validation · size/page limits · sandboxed parsing subprocess with limits · no HTML rendering of extracted content (text only; sanitise when HTML viewers arrive) · prompt-injection delimiting · secrets from env only · strict CORS allowlist · rate-limit hook middleware (no-op locally) · `audit_log` for upload, delete, chat, export.

Deferred to M-Prod: real auth, tenant-isolation tests at scale, malware scanning, signed S3 URLs, retention, backups, edge rate limiting, secret manager.

## 12. Compute

Startup probes hardware (CPU count, RAM, CUDA/MPS availability) and logs it. In v1 the heavy ML (generation, embeddings) runs on Gemini, so local compute is parsing only. Local models (reranker, OCR, ASR) arrive in later milestones with config for device, threads and max concurrency. On macOS, containers cannot use the Apple GPU; ML workers needing MPS run natively (documented in README).

## 13. Path to production

Cloudflare Pages (SPA) · container host for `api` + `worker` · managed Postgres with pgvector · R2 via `S3Storage` · OIDC via `AuthProvider` · Sentry/OTel via the observability wrapper. No code outside the interface implementations changes.
