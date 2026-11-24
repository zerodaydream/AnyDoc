# ADR-0001: PDF extraction with pypdfium2

Status: proposed (M0) · Date: 2026-11-25

## Context
Citations need exact char-offset → box mapping. AnyDoc will be hosted, so AGPL code in the server path forces source disclosure or a commercial licence.

## Decision
Use pypdfium2 (BSD-3/Apache-2.0) for char-level text, boxes and rendering. Write our own word, line, column and block grouping in `backend/extraction/formats/pdf/`.

## Evidence
Bench in `docs/TECHNOLOGY_EVALUATION.md` D1: word counts within ~3 % of PyMuPDF, comparable speed, lowest peak RSS (39–60 MB). pdfplumber defaults merged words on a tight-set paper and was 3–7× slower.

## Consequences
- We own reading-order heuristics; multi-column and tables need tests on real samples.
- Docling remains the upgrade path for layout if M2 eval shows failures.
- Extractor (PDFium) and viewer (pdf.js) differ; a coordinate-agreement test is mandatory in M1.
