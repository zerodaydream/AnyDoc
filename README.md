# AnyDoc

Open a document, ask it questions, and click any answer to see the exact evidence highlighted in the original file.

**Status:** M1 (PDF) and M3 (TXT, Markdown) built and tested; M2 waits for evaluation documents. Formats: PDF, `.txt`, `.md`. See `PROGRESS.md`.

## Run locally (default: Postgres in Docker, API + worker native)

Prerequisites: Docker Desktop running, `uv` ≥ 0.13, Python 3.13, Node 22.

```bash
cp .env.example .env                 # set GEMINI_API_KEY (empty => offline fake model)
docker compose up -d postgres
uv sync --all-extras
uv run python -m backend.migrate     # app schema + job-queue schema (idempotent)

# three terminals
uv run uvicorn backend.api.app:app --port 8000
uv run python -m backend.workers     # first start downloads the embedding model (~536 MB)
cd frontend/web && npm install && npm run dev   # http://localhost:5173
```

Model choice and thinking: list the models users may pick in `.env` (`LLM_MODELS=a,b,c`; `LLM_ANSWER_MODEL` is the
default), plus `LLM_THINKING_LEVELS` / `LLM_THINKING_DEFAULT` and `MAX_QUESTION_CHARS`. Restart the API after editing.

The worker uses the Apple GPU (MPS, bf16) when run natively. Startup fails loudly if a configured Gemini model does not exist or the key is invalid; an overloaded model (HTTP 503) only logs a warning.

## Run everything in Docker

```bash
docker compose --profile full up --build     # http://localhost:8080
```

Containers cannot use the Apple GPU, so embeddings run on CPU there (about 15× slower; see `docs/TECHNOLOGY_EVALUATION.md`).

## Tests

```bash
uv run pytest                                  # backend (needs the postgres container)
uv run ruff check backend && uv run mypy backend --exclude backend/tests
cd frontend/web && npx vitest run && npx tsc -b && npx eslint src
# end-to-end against a running stack, using any installed Chromium-based browser:
BROWSER="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" node e2e/smoke.mjs "" /tmp
```

## Evaluation

```bash
uv run python -m eval.runners.run_eval eval/datasets/attention_synthetic.jsonl
```

Results land in `eval/results/`. The bundled set is synthetic (agent-written on a public paper); real targets wait for the owner's documents (`docs/EVAL_TARGETS.md`).

## Docs
`MISSION.md` · `ARCHITECTURE.md` · `docs/TECHNOLOGY_EVALUATION.md` · `docs/DESIGN.md` · `docs/adr/` · `PROGRESS.md`

## Privacy
Traces sent to LangSmith hide document text and questions by default (`TRACE_CONTENT=true` opts in, dev test documents only). Embeddings run locally; only the blocks used to answer a question are sent to Gemini. Do not use a Gemini free-tier key with private documents.
