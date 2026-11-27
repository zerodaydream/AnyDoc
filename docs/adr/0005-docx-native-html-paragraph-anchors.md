# ADR-0005: DOCX renders as HTML in the browser; citations anchor to paragraphs by order

Status: accepted (M4) · Date: 2026-11-27

## Context
The brief asks to compare converting DOCX to PDF (LibreOffice headless, reuse the PDF viewer) with native HTML
rendering, and to prefer whichever lands citations accurately. LibreOffice is a ~700 MB install on an 8 GB machine
and turns the mapping problem into DOCX paragraph → PDF box. The owner chose native HTML (2026-11-27).

## Decision
1. The viewer renders the original .docx in the browser with docx-preview, `breakPages: false` (otherwise it splits
   a paragraph at a page break into two `<p>`s). Output is sanitised: http(s)/mailto links only, package images
   only, no embedded objects or fonts.
2. The backend reads the OOXML itself (stdlib zipfile + ElementTree) and numbers paragraphs in **exactly the order
   docx-preview renders them** (body, table cells, content controls; field codes and deletions skipped).
   `DocxLocation.regions[].para` is that index; offsets are code points into the paragraph's text.
3. Table blocks are rows written as `cell | cell`; each block keeps a segment map (content span → paragraph +
   offset), so a quote crossing cells becomes one region per cell paragraph.
4. Labels: "paragraph 15" (count of non-empty body paragraphs), "table 1, rows 2–3".
5. A parity test renders a generated .docx in jsdom and asserts the viewer's paragraphs equal the backend's, in order.

## Consequences
- Citations wash the right paragraph by construction; the exact quote is painted when the rendered text matches
  the offsets (always, except after a footnote marker in the same paragraph — then the paragraph wash still shows).
- Layout is close to Word, not page-exact: one long page per section, no page numbers.
- Upgrading docx-preview needs the parity test green; its traversal rules are now a contract.
- Headers, footers, footnotes and text boxes are shown but not read for answers in v1; comments are not shown.
