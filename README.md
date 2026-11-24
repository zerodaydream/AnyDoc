# AnyDoc

Open a document, ask it questions, and click any answer to see the exact evidence highlighted in the original file.

**Status:** M0 (research and plan) complete. No runnable code yet — M1 builds the foundation and the PDF vertical slice.

## Docs
- `MISSION.md` — what AnyDoc is for.
- `ARCHITECTURE.md` — system design, data model, citation protocol.
- `docs/TECHNOLOGY_EVALUATION.md` — every technology choice with evidence and licences.
- `docs/DESIGN.md` — UI tokens and layout.
- `docs/adr/` — architecture decision records.
- `PROGRESS.md` — what is done, blocked and next.

## Prerequisites (for M1)
- Docker Desktop (running), give it ~4 GB RAM.
- `uv` ≥ 0.13, Python 3.13, Node 22.
- Copy `.env.example` to `.env`. Without `GEMINI_API_KEY` the app runs with a fake LLM provider; without `LANGSMITH_API_KEY` tracing is a no-op.

## Privacy
Traces sent to LangSmith hide document text and questions by default. Set `TRACE_CONTENT=true` only for your own test documents. Do not use the Gemini free tier with private documents: Google may use free-tier content to improve its products.
