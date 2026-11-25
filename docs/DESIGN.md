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

## Layout

```
┌───────────────────────────────┬─┬──────────────────────────────────────┐
│ AnyDoc  ▾ report-q3.pdf       │ │  ◁ 4 / 38 ▷   − 110% +   ⌕   ⤢     │
│───────────────────────────────│ │──────────────────────────────────────│
│                               │ │ ┌────────────────────────────┐       │
│  You                          │ │ │                            │       │
│  What was Q3 revenue?         │ │ │  ...Revenue for the third  │       │
│                               │║│ │  ▌quarter was $4.2M, up 12%│ ◀ wash│
│  Q3 revenue was $4.2 million, │║│ │  ▌from Q2...               │       │
│  up 12% on the quarter.¹      │ │ │                            │       │
│  ① p. 4  "Revenue for the     │ │ └────────────────────────────┘       │
│     third quarter was $4.2M"  │ │                                      │
│                               │ │                                      │
│ ┌───────────────────────────┐ │ │                                      │
│ │ Ask about this document   │ │ │                                      │
│ └───────────────────────────┘ │ │                                      │
└───────────────────────────────┴─┴──────────────────────────────────────┘
   chat ~40% (min 320px)       divider        viewer ~60%
```

- Chat is left-aligned and reads like a page: no bubbles for the assistant, a quiet surface tint for user turns.
- Viewer canvas is `--sunken`, pages float on it with a 1px `--line` edge, no drop shadow.
- Divider: 1px line, 8px hit area, grip appears on hover/focus; arrow keys resize; double-click resets.
- Mobile (< 768px): one panel at a time with a two-tab switch (Chat / Document); tapping a citation switches to Document and scrolls.

## The one bold thing: the evidence jump
Everything else stays quiet so this lands.
- Citations are serif superscript numerals in clay inside the answer, plus a compact evidence row under the paragraph (page + the verified quote, truncated). Numbers are justified: citations are an ordered sequence.
- Clicking one scrolls the viewer and paints the evidence wash with a 2px clay rule on the left edge of each region. One 240 ms ease-out fade-in of the wash is the only unprompted motion in the product; reduced-motion users get it instantly.
- Multi-region citations show "1 of 3" stepping in the viewer toolbar.
- Low-confidence evidence uses `--warn` with a dotted underline and a tooltip stating the confidence.

## States (copy)
- Empty workspace: "Drop a PDF here or choose a file. Answers will link to the exact page and line." Button: "Choose file".
- Processing: step list with live state — Uploading, Checking file, Reading pages (12 of 38), Indexing, Ready.
- Failed: say what and what to do. "This PDF couldn't be opened: the file is damaged. Try exporting it again." Button: "Upload another file".
- Abstain: "The document doesn't say." followed by the closest passages it did check, each clickable.
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
