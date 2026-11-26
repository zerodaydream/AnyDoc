# Progress

Read this first every session. Update it last.

## Current state (2026-11-26)
- M0 — done (research, plan; owner answered clarifications).
- **M1 — Foundation + PDF vertical slice: built and tested, awaiting owner review.**
- M2 — blocked until the owner supplies evaluation documents in `eval/data/`.
- **M3 — TXT/Markdown: built and tested; live Gemini eval baseline still to run.** Owner chose (2026-11-26) to do
  M3 ahead of M2 because M2 is blocked.

## Groq provider + picker tabs (2026-11-27, owner request, uncommitted, not pushed)
- `GROQ_API_KEY` adds a Groq tab to the model picker next to Gemini; `backend/llm/router.py` sends each request to
  the picked model's provider. `LLM_PROVIDER` picks the default tab. Gemini flow unchanged.
- Groq models (config.json `GROQ_MODELS_ENABLED`): qwen/qwen3.8-27b (thinking off by default; "off*" spec, now
  supported for any model), openai/gpt-oss-120b and -20b (low/medium*/high). Reasoning shows as the thought block.
- One JSON-mode call per answer; `GROQ_CONTEXT_TOKEN_BUDGET=4000` (free plan: 7,000 input tokens/min); passage
  search trims to the budget. Verified live with the owner's key (TECHNOLOGY_EVALUATION D10).
- Tests: `backend/tests/test_groq_provider.py`, `frontend/web/src/features/chat/modelTabs.test.tsx`.

## Failed answers always get a readable reply (2026-11-27, owner request, uncommitted)
- Engine: retrieval now runs inside the guarded block, so a question always gets a saved assistant message (it used
  to be left with no reply when retrieval failed). Errors are stored in `usage.error` (our wording only) and
  returned as `MessageOut.error`. New wording covers model busy (`llm_busy`) and a general failure (`answer_failed`).
- UI: an error reply shows the AnyDoc mark + an alert line. Older questions with no saved reply show
  "No answer was saved for this question. Try asking again."
- Tests: `test_retrieval_failure_still_saves_a_readable_reply`, busy-message assert, frontend failed-answer test.

## Brand mark + animated answer row (2026-11-27, owner request, uncommitted)
- Owner's logo and wordmark replace the old mark (`components/Logo.tsx`, theme-aware `--logo-*` tokens, favicon).
- Answers render beside an animated `LogoMark` (thinking / streaming / idle; draw-in on a new answer). See DESIGN.md.
- Tests: 2 new in `AssistantMessage.test.tsx`. Verified visually in Brave (dark + light, thinking frames).

## Gemini retry policy (2026-11-27, owner request, uncommitted)
- Follows Google's retry guidance: exponential backoff + jitter, only 408/429/5xx and network errors, max 5 attempts.
- Done with the SDK's own `HttpRetryOptions` (google-genai 3.6.1 retries **only** if `retry_options` is set; verified
  in `_api_client.retry_args`). Waits ~1/2/4/8 s + ≤1 s jitter, 60 s cap. Hand-rolled loops in
  `stream_json`, `web_answer`, `check` removed. Stream failures after output starts are not retried by the SDK;
  they still surface as `TransientError` and the engine resets + restarts once.
- Tests: `backend/tests/test_gemini_retry.py` (5 attempts on 503, 1 on 400, backoff params).
- Note: each attempt has its own `LLM_TIMEOUT_S`, so worst case ≈ 5 × timeout + backoff.

## M3 — TXT / Markdown (2026-11-26, uncommitted)
- Format module `backend/extraction/formats/text/`: decode (BOM → UTF-8 → Windows-1252 → reject, newlines
  normalised; mirrored in `viewers/text/text.ts`), plain-text paragraphs + conservative heading guesses (ALL CAPS,
  underlined, short numbered, run-in "2. Title."), Markdown blocks from markdown-it-py `token.map` (front matter,
  headings with nested section paths, list items, quotes, code, tables). Block content = exact source slice; long
  blocks split at line/sentence/word boundaries (≤ 2,000 chars). Limit `MAX_TEXT_CHARS` (2,000,000).
- `TextLocation` (code-point offsets + 1-based lines), locator + label (ADR-0004). One-time generalisation so later
  formats don't touch chat/citations/upload: citations, closest passages and outline carry `ref` ("lines 12–14");
  prompt says `location="…"`; handlers declare `label`, `media_type`, `extent()`; `GET /api/formats` drives the
  upload screen; `DocumentOut.extent` replaces "N pages" in the UI. Old stored citations fall back to `page`.
- Viewer `viewers/text/TextViewer.tsx`: source sheet, line numbers, Markdown styling, evidence marks + margin pin,
  ~30% placement, find, zoom, lazily rendered 200-line groups. Registered for `text` and `markdown`.
- Fixed on the way: eval runner used the removed `/api/documents/{id}/messages` endpoint (now one session per
  question); upload screen rejected non-PDF files picked before `/api/formats` loaded; chunk prefix uses the
  deepest heading; markdown-it-py declared directly (it was only transitive via the `ml` extra); `mypy --strict`
  on tests is clean again. Vite proxy target is `API_URL` (default `http://localhost:8000`).
- Eval: `apache_txt_synthetic` (14) and `zustand_md_synthetic` (13) with gold line ranges, checked by
  `eval/runners/check_gold.py`. **Not run against Gemini yet** (no key in the agent session).
- Tests: backend 87 (25 new: decoding, sniffing, block types, exact offsets incl. emoji, splitting, limits,
  malformed/binary/undecodable files, sandbox, locator, validator, API upload→ask→cite, formats). Frontend 50
  (16 new: decode parity, preview sanitising + line anchors + quote matching + toggle, code-point mapping, line marks, Markdown styling, find, viewer highlight/pin/find,
  citation click-through). E2E `frontend/web/e2e/text-smoke.mjs` green on the Markdown and TXT docs (isolated
  stack, fake model): pin on the first cited line, marks only on cited lines, evidence in view; dark, light, mobile
  screenshots reviewed.

- **Markdown Preview (owner request):** "Preview | Markdown" toggle at the viewer toolbar's top right (generic
  `ViewerState.modes`), Preview default, choice remembered. Rendered with markdown-it 15 (new frontend dep, evidence
  in TECHNOLOGY_EVALUATION D8), blocks anchored by source line; citations wash the block, paint the exact quote
  (CSS Highlight API) and pin; find works in both views. Sanitised: no raw HTML, no image loads, only http(s)/mailto
  links. Verified in Brave on the owner's `freya_workbench_poc` plan file; e2e covers both views.

- **Stop (owner bug report 2026-11-26):** Stop left the answer "streaming" (status line + stop button stayed),
  showed the question twice once history reloaded, and the server's save was cancelled with the request (question
  left without an answer). Now: the engine records a `stopped` answer keeping only verified segments, saved in a
  shielded scope; the UI ends the stream, drops unverified text, shows "Response stopped." and dedupes the question
  by `user_message_id`. Tests: backend stop-recording, reducer/message, ChatPanel stop flow.

- **Fuller answers + suggestion; preview highlight polish (owner request 2026-11-26):** prompt asks for the direct
  answer plus the supporting details the blocks give (often 3–6 cited segments, no padding). `AnswerOut.suggestion`
  is an optional, uncited next step (follow-up question / where to look), streamed as a `suggestion` event after
  validation, sent only for answers that cite something, capped at 400 chars, stored in `messages.suggestion`
  (migration 0004), shown under the answer with a lightbulb; dropped on stop/error/abstain. Preview wash is now a
  `::before` swiped in left to right (420 ms; off with reduced motion); list items put the bar left of the bullet;
  fenced code (e.g. file trees) is washed as one `<pre>` block instead of per-line strips, with the quote painted.
  Checked in Brave via a static CSS harness (bullet clearance, single tree block, swipe mid-frame); not yet with live
  Gemini answers.

- **Web lookup + config.json (owner request 2026-11-26):** `backend/config.json` holds product settings
  (`MODELS_ENABLED` model → levels with `*` default, replacing `LLM_MODELS`/`LLM_MODEL_THINKING`; limits; models;
  `WEB_SEARCH_ENABLED`; `APP_ENV`; `LANGSMITH_TRACING`; …). `.env` keeps secrets and machine values and overrides
  config.json, as does any env var (`ANYDOC_CONFIG_FILE=""` disables it in tests). The owner's `.env` was trimmed;
  the original is at `.env.bak`. Web lookup (D9): the answer schema gets `web_query`; on abstention or a web_query,
  one Gemini Google-Search-grounded call runs (separate from the schema call) and keeps only attributed text; it is
  streamed as `web_searching` → `web`, stored in `messages.web` (migration 0005), and shown as "From the web" with
  sources and a sandboxed Google chip. **Not verified live: the owner's key gets 429 on every grounded call.**

### M3 known limitations
- Preview highlights are block-level when the quoted words aren't contiguous in rendered text (e.g. a quote that
  includes a link URL); the Markdown view is always exact. Images in Markdown are never loaded.
- Plain-text heading detection is heuristic; numbered-list lines of ≤ 6 words can be taken as headings.
- Wrapped lines in hard-wrapped TXT don't keep their indent.
- Find is disabled for texts whose lower-casing changes length (rare scripts).
- Large-file behaviour (2M chars) not measured. Encodings other than UTF-8/UTF-16/Windows-1252 are rejected.

## Post-M1: model choice + thinking (2026-11-25, owner request, uncommitted per owner)
- `.env`: `LLM_MODELS` (picker list; `LLM_ANSWER_MODEL` is the default and always included), `LLM_THINKING_LEVELS`,
  `LLM_THINKING_DEFAULT`, `MAX_QUESTION_CHARS`. `GET /api/models` returns each model's input/output token limits and
  whether it thinks (from `models.get`, no generation), the allowed levels and the question limit.
- Ask accepts `model` + `thinking` (level or `off`), validated against the lists (422 otherwise). Gemini
  `ThinkingConfig(thinking_level, include_thoughts=True)`; thought parts stream as `thinking_delta`, are stored in
  `messages.reasoning` (migration `0003`), and are never treated as evidence. A model rejecting an option (HTTP 400)
  returns `unsupported_option` with the model's message. Internal aliases in reasoning ("Block b130") are shown as pages.
- UI: composer has Thinking and Model menus (remembered per browser) and a `n / 4,000` character counter. Claude
  Code–style thinking block: turning clay ✻ glyph + shimmering "Thinking" + timer and latest-line preview while live;
  collapses to "✻ Thought for 8.4s", expands to the summary (headings/bold rendered) with a note that only the
  answer is checked. Thinking time = request start → first answer text.
- Verified live: `gemini-3.5-flash-lite` reports `thinking: true`, 1,048,576 input tokens; MEDIUM returns thought
  summaries. Other levels and other models were not probed live (owner declined the sweep) — unsupported combinations
  surface as a clear error.
- Per-model levels: `LLM_MODEL_THINKING` JSON (`{"model":"low,medium*,high"}`, `*` = default) from the owner's
  table (unverified by us). Menu shows only the selected model's levels; server and client clamp unsupported picks
  to the nearest level (minimal->low, xhigh->high). Failed model lookups are cached 5 min (picker loads fast).
  Live: 8 of 10 configured models available; `gemini-3.1-pro-preview` and `gemini-3-flash-preview` are not
  accessible with the current key (shown disabled).
- Sidebar tooltip: full conversation title on hover/focus when truncated; palette tokens; 140 ms fade/slide.
- Tests: backend 59, frontend 34, e2e with real thinking green.

## Post-M1 change (2026-11-25, owner request)
- `.env` is authoritative over shell env (pydantic-settings source order); tests opt out via `ANYDOC_ENV_FILE=""`.
- **Conversations:** `chat_sessions` table (migration `0002`, reversible, existing history migrated one session per
  document). API `/api/sessions` (list, create, rename, delete, messages, ask). The model's context is the open
  session only — verified by a test that a second session on the same document never sees the first's questions.
  Title = first question (cut at a word boundary). `/api/documents/{id}/outline` returns headings.
- **UI redesign:** collapsible sidebar with grouped conversations (rename, two-step delete, Ctrl/Cmd+B, mobile
  drawer), home view, grounded section starters, quote-block sources, numbered pills, "what is being read" status,
  **margin notes** (numbered clay tab pinned beside the evidence), Sections menu, typed page jump, evidence placed
  ~30% down so the toolbar shows the cited page. Design notes in `docs/DESIGN.md`.
- Alembic now ignores procrastinate tables and declares the GIN/HNSW indexes (`alembic check` clean).
- Tests: backend 45, frontend 21, e2e smoke (new flow, real Gemini) green.

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
1. Restart the dev worker (it predates M3), then run the TXT/MD baselines against Gemini:
   `uv run python -m eval.runners.run_eval eval/datasets/apache_txt_synthetic.jsonl` and `…/zustand_md_synthetic.jsonl`,
   and re-run `attention_synthetic.jsonl` for PDF regressions (prompt now says `location=` instead of `page=`).
2. Owner review of M1 + M3. 3. M2 once evaluation documents arrive. 4. M4 DOCX after that.
