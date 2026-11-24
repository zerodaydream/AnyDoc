# ADR-0002: Streamed structured output with per-segment citation validation

Status: proposed (M0) · Date: 2026-11-25

## Context
The brief needs streaming answers AND never showing an unvalidated citation. Free-text with inline markers is fragile; waiting for the full answer kills streaming.

## Decision
The model streams schema-constrained JSON (`status`, `segments[{text, evidence[{block_id, quote}]}]`). An incremental parser forwards segment text as `text_delta` SSE events. On segment close, the backend validates its evidence and emits `citation` or `segment_retracted`. Locations come only from the IR.

## Consequences
- Users see text immediately; chips appear a moment later, only when verified.
- A segment may be retracted after display; the UI handles that state explicitly.
- Requires the configured model to support streaming structured output — checked by the startup smoke test (not confirmed from Gemini docs at M0).
- Fallback if streaming structured output is unavailable: non-streamed structured call, then simulated progressive reveal of validated segments.
