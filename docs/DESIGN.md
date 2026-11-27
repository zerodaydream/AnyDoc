# AnyDoc design system

Brief from the owner: **a Claude-style UI, dark mode first.** That pins the visual direction (warm charcoal surfaces, warm off-white text, clay accent, serif reading voice). Light theme ships too (brief §3). AnyDoc keeps its own name and wordmark; it does not use Anthropic logos, the Claude spark mark or the word "Claude" anywhere in the product.

**Theme behaviour (owner decision):** the app always opens dark, whatever the OS setting. A toggle in the header switches to light; the choice is remembered per browser. No "follow system" mode.

## Subject, audience, job
- **Subject:** reading a document and checking answers against it.
- **Audience:** people who verify — analysts, researchers, lawyers, students.
- **Primary job of the screen:** make the jump from a claim to its evidence instant and unmistakable.

## Color tokens

Dark (default):

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#262624` | App background, chat column |
| `--surface` | `#30302E` | Composer, popovers, viewer chrome |
| `--sunken` | `#1F1E1D` | Viewer canvas behind pages, sidebar |
| `--line` | `#3E3E38` | Hairline borders, divider |
| `--text` | `#F5F4EE` | Primary text |
| `--text-muted` | `#B7B5A9` | Secondary text, metadata |
| `--accent` | `#D97757` | Clay: citations, focus ring, primary action |
| `--accent-strong` | `#E08A6D` | Hover / active on dark |
| `--evidence` | `rgba(217,119,87,0.22)` | Highlight wash in the viewer |
| `--warn` | `#D4A54A` | Low-confidence (OCR/ASR) evidence |
| `--danger` | `#E06C5B` | Errors |

Light:

| Token | Hex |
|---|---|
| `--bg` | `#FAF9F5` |
| `--surface` | `#F0EEE6` |
| `--sunken` | `#E8E6DC` |
| `--line` | `#DAD7CC` |
| `--text` | `#1F1E1D` |
| `--text-muted` | `#5E5D59` |
| `--accent` | `#AD5434` (darker clay: 4.87:1 with light text, checked by the token contrast test) |
| `--evidence` | `rgba(173,84,52,0.18)` |

All text/background pairs are checked to WCAG AA in M1 with an automated contrast test.

## Type
- **Reading voice — Source Serif 4** (variable, OFL). Assistant answers and document titles. 17/28 px in chat, max 68 ch.
- **Interface — Hanken Grotesk** (variable, OFL). Buttons, inputs, user messages, viewer chrome. 14/20 base.
- **Code — JetBrains Mono** (OFL). Only inside code blocks; never for labels or metadata.
- Self-hosted through `@fontsource-variable/*` packages; no runtime font CDN (privacy, offline).
- Scale (1.2 ratio): 12 · 14 · 17 · 20 · 24 · 29. Sentence case everywhere. No all-caps labels.

## Layout (revised 2026-11-25: owner asked for session history and a less bland UI)

```
┌─────────────┬───────────────────────────────┬─┬────────────────────────────────────┐
│ ▢ AnyDoc  ⟨ │ Which optimizer was used…     │ │ ☰ Sections  [7] of 15  ⌕ Find − 84% + ⤢│
│ ⊕ New conv. │───────────────────────────────│ │────────────────────────────────────│
│             │            ╭───────────────╮  │ │   5.3 Optimizer                    │
│ Today       │            │ user question │  │ │ ┌1┐ ▌We used the Adam optimizer… ◀ wash
│ ▌Which opt… │            ╰───────────────╯  │ │   rate over the course of training │
│  attention  │ The Adam optimizer was used 1 │ │                                    │
│ How many…   │ ┃1 “We used the Adam…”  Page 7 │ │                                    │
│  attention  │ ╭───────────────────────────╮ │ │                                    │
│ ☀ Light     │ │ Ask about this document  ↑│ │ │                                    │
└─────────────┴───────────────────────────────┴─┴────────────────────────────────────┘
 sidebar 264px     conversation ~42% (≥360px)        document ~58% (≥360px, collapsible)
```

- **Sidebar** (`--sunken`): wordmark, New conversation, conversations grouped Today / Yesterday / Previous 7 days /
  Previous 30 days / Older; each row = title (first question) + document name. Rename (double-click or pencil),
  delete (two-step confirm). Collapses to zero width (Ctrl/Cmd+B); a drawer on narrow screens. A conversation
  appears in the list once it has a first question.
- **Home** (no conversation open): serif headline, drop zone, and "Click to converse with your old document uploads" recent documents.
- **Conversation**: header with the conversation title; user turns are right-aligned bubbles; answers are serif
  prose with numbered clay pills; sources below as quote blocks (clay rule, italic serif quote, page). Before the
  first word (and while no thoughts arrive): plain status lines that step through every answer's stages every
  2.4 s and rest on the last ("Reading through your document…" … "Putting the answer together…"). No counts or
  internals (`features/chat/waitLines.ts`).
- **Empty conversation**: document chip, "What would you like to know?", and "Or start with a section" — the
  document's real headings with page numbers (from `/outline`), so starters are grounded, never invented.
- **Viewer**: Sections menu, typed page jump, evidence-location stepper (multi-region), find, zoom.
- Mobile (< 900px): top bar with menu + wordmark, Conversation / Document tabs.

## Text viewer (M3, TXT and Markdown)
- The source itself on a sheet (same hairline edge as PDF pages), with muted line numbers in a gutter. Nothing is
  reflowed or rendered: a citation is a character range, and the reader sees exactly what was quoted.
- **Plain text uses JetBrains Mono** (a deliberate exception to "mono only in code"): TXT files rely on
  fixed-width alignment. Ligatures are off so `=>` stays two characters.
- **Markdown uses the serif reading voice**; heading lines are larger and semibold, code fences, tables and front
  matter switch to mono on a `--surface` band, block quotes get a muted rule. Markers (`#`, `-`, `>`) stay visible.
- Evidence: `--evidence` wash with a 1 px clay underline per marked run; the margin note (numbered clay tab)
  replaces the line number of the first cited line. Find matches use the warn wash; the current one is outlined.
- Citations everywhere say where in the format's own words: "Page 7", "Lines 12–14".
- **Markdown Preview** (default; toggle "Preview | Markdown" at the toolbar's right, remembered per browser):
  rendered in the serif reading voice on the same sheet, max 860 px; h2 with a hairline rule; inline code as
  bordered `--surface` chips; code blocks mono, no wrap; tables in the interface face. Front matter folds into
  "Front matter · N lines". Images show as dashed alt-text chips (never loaded). Cited block: light evidence wash
  with a clay rule in the margin; the exact quote gets the full `--evidence` wash; pin in the left margin.

## Word viewer (M4, DOCX)
- docx-preview pages sit on the sunken canvas with a hairline edge and no shadow, like PDF pages. The page keeps
  the document's own colours, so it stays paper-white in both themes. Opens fitted to the panel width (max 125%),
  re-fits on resize until the reader zooms by hand.
- Cited paragraph: the Markdown preview's wash + clay bar, swiped in; the exact quote gets the full `--evidence`
  wash (CSS Highlight API); the numbered pin sits in the page margin beside the first cited paragraph. A quote
  across table cells washes each cell's paragraph. Find paints all matches and the current one.

## CSV viewer (M5)
- The table as a sheet on the sunken canvas: hairline cells, a sticky header row on `--surface` (weight 600) and a
  sticky row-number gutter. Interface face with tabular figures; number columns right-aligned. Files without a header
  show muted "Column A…" names. Row numbers are the file's records, so they match citation labels ("row 12, Total").
- Evidence: cited cells get the `--evidence` wash with a 2 px clay underline (240 ms fade, none with reduced motion);
  the numbered pin replaces the row number of the first cited row. A computed answer washes every cell it read;
  the toolbar stepper walks those regions. Find washes matches in warn; the current one is outlined.
- Only rows and columns in view are in the DOM (`role=grid` with row/column indexes for screen readers).

## Brand mark (2026-11-27, owner artwork)
- Owner-supplied artwork lives in `frontend/web/src/components/Logo.tsx`: `Wordmark` (page icon + bold Georgia
  "AnyDoc", sidebar and mobile top bar) and `LogoMark` (24×24 artwork, shown at 32 px beside answers). Favicon: `public/favicon.svg`.
- Colours are `--logo-ink / --logo-line / --logo-spark`. Light uses the owner's originals (#29231F, #CDB394, #C97850).
  Dark lifts them for contrast on charcoal (#EDE7DD, #BFA586, #E08A62).
- Claude-style answer row: `LogoMark` sits left of every answer, and the answer streams beside it. A new answer draws the
  page in, then pops the sparkle. While thinking, the sparkle shrinks, swells and turns, and the lines are read in turn.
  While text streams, it twinkles softly. Once done, it is still. All of this motion answers the user's question.
  Reduced motion: no animation.

## The one bold thing: margin notes
The evidence jump is the product. Clicking citation *n* paints the clay wash over the exact lines **and pins a
numbered clay tab in the page margin** beside the first line, the same numeral as the pill in the answer, like an
annotation in a printed book. The viewer scrolls so the evidence sits ~30% down the viewport (context above it, and
the toolbar reports the cited page). The 240 ms wash fade is the only unprompted motion; reduced-motion users get
none. Low-confidence evidence uses `--warn` for wash, pill and pin.

## States (copy)
- Empty workspace: "Drop a PDF here or choose a file. Answers will link to the exact page and line." Button: "Choose file".
- Processing: step list with live state — Uploading, Checking file, Reading pages (12 of 38), Indexing, Ready.
- Failed: say what and what to do. "This PDF couldn't be opened: the file is damaged. Try exporting it again." Button: "Upload another file".
- Abstain: "I couldn't find an answer to this in your document." then what happens next: ", so I'm checking the web
  as well." while the web search runs (", so I checked…" after), otherwise "Asking it in other words may help." and
  the closest passages it did check, each clickable.
- Citation dropped during streaming: the sentence fades to muted with "Removed: couldn't verify against the document."

## Principles
1. Evidence beats prose. If space is tight, keep the citation, cut the sentence.
2. Quiet chrome. Icons from Lucide at 16px, borders before fills, no gradients, no shadows on cards.
3. Warmth from color and type, not decoration.
4. Every motion answers an action, except the evidence wash.
5. Keyboard first: `/` focuses the composer, `[` `]` step citations, `Ctrl+\` toggles the viewer, visible 2px clay focus ring everywhere.

## Review against the brief
- The brief asks for the Claude look, so the warm-charcoal + clay + serif palette that the frontend-design skill lists as a common default is used **on purpose**, per the owner's words.
- Changed from a first draft: dropped a monospace face for page/coordinate labels (template tell) — page refs use the UI sans. Dropped an "EVIDENCE" all-caps eyebrow above citation rows — the clay numeral already says it. Dropped middle-dot metadata strings in the toolbar in favour of separate controls.
