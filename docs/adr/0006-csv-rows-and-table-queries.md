# ADR-0006: CSV is read as cell-mapped row blocks, and computed with declarative table queries

Status: accepted (M5) · Date: 2026-11-28

## Context
Brief §6.7: tabular formats must not only be flattened into chunks. Questions like "total sales in the West" need
every row, and a model doing arithmetic over retrieved rows is neither complete nor reliable. Brief §10 asks for
*sandboxed* query execution. Rule 6: a new format must not touch chat, citations, workspace or the core pipeline.

## Decision
1. **Parsing** (`formats/csv/table.py`): our own RFC 4180 tokeniser (Python's csv semantics, strict=False) so the
   viewer can mirror it exactly; an unclosed quote fails the file instead of swallowing it. Delimiter = the candidate
   (`,` tab `;` `|`) whose first 50 records agree best on a field count ≥ 2. Header = heuristic (filled, non-numeric,
   not repeated below), tried on record 1, then below up to 10 title lines (blank or sparsely filled records, e.g. a
   report title). Title lines are the preamble: one block of their own, shown in the viewer, never data rows. Rows
   are file records from 1 (header and preamble included, blank lines count), like a spreadsheet.
2. **Blocks**: runs of ≤ 40 rows / ~1,500 chars, each led by `Columns: …`; lines are `Row 12: a | b | c`. Every cell's
   span is recorded, so a verified quote maps to exact cells. Retrieval (full context or hybrid) is unchanged.
3. **Table queries** (`formats/csv/query.py`): before answering, one planning call gets the table's schema (names,
   types, counts, 3 example values) and returns a `TablePlan` — conditions, group-by, one of
   count/sum/average/median/min/max/count_distinct/rows. **No code, SQL or expressions.** The plan runs over the whole
   original file in the parsing sandbox (`QUERY_TIMEOUT_S`, `PARSE_MEMORY_MB`). Each result becomes an evidence block
   in the section "Computed from the whole table by AnyDoc", whose segments map to the cells actually read (matched
   rows × condition/group/value columns; min/max to the rows holding the extreme).
4. **Evidence text never contains model-written strings**: a filter value is printed only when that text is found in
   the column (in the file's spelling), or when it is a plain number or ISO date. Otherwise: "a value that isn't in
   this column". Unknown columns or wrong types drop the query; nothing is guessed. A number column needs at least
   half of its filled cells to be numbers: sum/average/median use the numbers and the evidence names the cells left
   out (e.g. version ranges "3.9-3.93"), so the answer can say so. The schema shows the planner that count.
7. **No web fallback for table questions**: when the planner returned queries, the question is about the file's own
   rows, so an empty or failed computation abstains instead of searching the web.
8. **Title lines are named, never counted**: when title lines hold text in a column a query read, the evidence adds
   `Above the table (title lines, not data rows): rows 1–2 have text in "Column A"`, cited to those cells, so a
   "0 rows" result can be explained instead of looking wrong.
5. **Generic hook, one time**: `registry.QueryTool` (plan schema, plan prompt, `run`) and
   `answering/computed.py`. The engine only prepends computed blocks; validation, locations and the UI are unchanged.
   One prompt rule was added: never do arithmetic; cite computed blocks for totals/counts.
6. **Numbers keep the column's decimals** (a sum of `12.50`-style prices prints `1250.00`), because the numeric
   check compares the strings an answer writes with the cited text.

## Consequences
- Aggregates are exact over every row and cite the cells behind them; a wrong number can't pass validation.
- One extra LLM call per CSV question (~schema-sized input). Planning/running failures degrade to row-only answers.
- Query time re-reads the original (source of truth) per question: bounded by `MAX_TEXT_CHARS`.
- XLSX (M6) can reuse the QueryTool hook, location kind and grid.
- Not supported: joins, arithmetic between columns, decimal commas (`1.234,5`), date formats other than ISO for
  ordering, more than 3 queries per question.
