# ADR-0004: Text locations are character offsets; the viewer shows the source

Status: accepted (M3) · Date: 2026-11-26

## Context
TXT and Markdown are the first formats after PDF. Chat and citation code had PDF pages built in ("Page 7",
`page="7"` in the prompt, `p. 7` on starters). The brief requires that a new format not touch chat, citations,
workspace or the core pipeline.

## Decision
1. `TextLocation{kind:"text", regions:[{char_start, char_end, line_start, line_end}]}`: code-point offsets into the
   decoded, newline-normalised file text; lines 1-based inclusive. TXT and Markdown share this kind.
2. Block content is the exact source slice, so the backend maps a verified quote by adding the block's start offset.
3. Each format registers a **label** function next to its locator. The backend sends `ref` ("page 7",
   "lines 12–14") with every citation, closest passage and outline item, and uses it in the prompt
   (`location="lines 12–14"`). Chat and citation UI show `ref`, never a page number.
4. Format handlers also declare `label`, `media_type` and `extent()` ("15 pages", "1,240 lines");
   `GET /api/formats` lists what can be uploaded, so the upload screen needs no change per format.
5. The text viewer shows the source (line numbers, cosmetic Markdown styling). **Amended 2026-11-26 (owner):**
   Markdown also has a rendered Preview (default), toggled with Preview | Markdown in the toolbar. Preview
   anchors blocks by source line (markdown-it `token.map`) and paints the exact quote where it can; the source
   view stays exact to the character. Viewers declare display modes in `ViewerState.modes`; the toolbar shows them.

## Consequences
- DOCX, CSV, JSON… add a location kind, a locator and a label; chat, citations and the upload UI stay untouched.
- Markdown is read as source, which suits checking evidence but is less pretty than a rendered page.
- Messages stored before this change have no `ref`; the UI falls back to `page`.
