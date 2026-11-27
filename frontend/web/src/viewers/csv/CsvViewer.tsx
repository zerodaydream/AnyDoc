import { useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import type { CsvRegion, SourceLocation } from '../../lib/api'
import type { Highlight, ViewerProps } from '../core/contract'
import { cellText, isNumeric, readTable, type Table } from './csv'

const ROW_H = 28 // px at 100%
const OVERSCAN = 8
const MIN_SCALE = 0.6
const MAX_SCALE = 2
const SAMPLE_ROWS = 300
const MAX_FIND = 10_000
const csvRegions = (l: SourceLocation): CsvRegion[] => (l.kind === 'csv' ? l.regions : [])

type Layout = { widths: number[]; lefts: number[]; total: number; numeric: boolean[]; gutter: number }

/** Column widths from the header and the first rows (at 100%); number columns are right-aligned. */
function measure(t: Table): Layout {
  const sample = t.rows.slice(0, SAMPLE_ROWS + 1)
  const widths: number[] = []
  const numeric: boolean[] = []
  t.columns.forEach((name, c) => {
    let longest = name.length
    let filled = 0
    let nums = 0
    sample.forEach((r, i) => {
      const v = cellText(r[c] ?? '')
      longest = Math.max(longest, Math.min(48, v.length))
      if (v && (t.headerIndex === null || i > t.headerIndex)) {
        filled++
        if (isNumeric(v)) nums++
      }
    })
    widths.push(Math.min(360, Math.max(64, Math.round(longest * 7.4 + 26))))
    numeric.push(filled > 0 && nums >= 0.9 * filled)
  })
  const lefts: number[] = []
  let x = 0
  for (const w of widths) {
    lefts.push(x)
    x += w
  }
  return { widths, lefts, total: x, numeric, gutter: Math.max(48, String(t.rows.length).length * 8 + 28) }
}

/** Cells containing `query` (case-insensitive), as [row, col] in reading order. */
function findCells(t: Table, query: string): [number, number][] {
  const q = query.toLowerCase()
  const out: [number, number][] = []
  for (let i = 0; i < t.rows.length && out.length < MAX_FIND; i++) {
    t.rows[i].forEach((v, c) => {
      if (cellText(v).toLowerCase().includes(q)) out.push([i + 1, c])
    })
  }
  return out
}

/** Index of the last column starting at or before `x`. */
function colAt(lefts: number[], x: number): number {
  let lo = 0
  let hi = lefts.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (lefts[mid] <= x) lo = mid
    else hi = mid - 1
  }
  return lo
}

/**
 * CSV as a virtualised grid: only the rows and columns in view are in the DOM. Row numbers are the file's records,
 * as the backend counts them. The header record is pinned on top; title lines above it (the preamble) are the first
 * body rows, so every record is shown once, in file order. Citations wash their cells, pin the note in the row gutter and
 * scroll the first cell ~30% down, like the other viewers.
 */
export default function CsvViewer({ src, ref, onState }: ViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [loaded, setLoaded] = useState<{ src: string; table: Table } | null>(null)
  const table = loaded?.src === src ? loaded.table : null
  const [scale, setScale] = useState(1)
  const [view, setView] = useState({ top: 0, left: 0, w: 0, h: 0 })
  const [hl, setHl] = useState<Highlight[]>([])
  const [find, setFind] = useState<{ query: string; step: number; matches: [number, number][] } | null>(null)
  const onStateRef = useRef(onState)
  useEffect(() => {
    onStateRef.current = onState
  })

  useEffect(() => {
    const ctl = new AbortController()
    onStateRef.current({ status: 'loading' })
    fetch(src, { signal: ctl.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`The file could not be loaded (${r.status}).`)
        return r.arrayBuffer()
      })
      .then((buf) => {
        if (!ctl.signal.aborted) setLoaded({ src, table: readTable(buf) })
      })
      .catch((err: Error) => {
        if (!ctl.signal.aborted) onStateRef.current({ status: 'error', message: err.message || 'The CSV file could not be displayed.' })
      })
    return () => ctl.abort()
  }, [src])

  useEffect(() => {
    if (table) onStateRef.current({ status: 'ready', scale })
  }, [table, scale])

  const base = useMemo(() => (table ? measure(table) : null), [table])
  const rowH = ROW_H * scale
  const hi = table?.headerIndex ?? null // index in table.rows of the header record (pinned on top)
  const bodyCount = table ? table.rows.length - (hi === null ? 0 : 1) : 0
  const recordAt = (i: number) => (hi === null || i < hi ? i : i + 1) // body position -> index in table.rows
  const gutter = (base?.gutter ?? 48) * scale
  const lefts = useMemo(() => base?.lefts.map((x) => x * scale) ?? [], [base, scale])
  const width = gutter + (base?.total ?? 0) * scale

  useLayoutEffect(() => {
    const el = containerRef.current
    if (!el || !table) return
    const sync = () => setView({ top: el.scrollTop, left: el.scrollLeft, w: el.clientWidth, h: el.clientHeight })
    sync()
    const ro = new ResizeObserver(sync)
    ro.observe(el)
    return () => ro.disconnect()
  }, [table])

  // row is 1-based; body position p sits at rowH * (p + 1), under the pinned header
  const rowTop = (row: number) => (hi !== null && row === hi + 1 ? 0 : rowH * (hi !== null && row > hi + 1 ? row - 1 : row))
  const scrollToCell = (row: number, col: number) => {
    const el = containerRef.current
    if (!el || !base) return
    const top = Math.max(0, rowTop(row) - el.clientHeight * 0.3)
    const x = lefts[col] ?? 0
    const inView = x >= el.scrollLeft && x + (base.widths[col] ?? 0) * scale <= el.scrollLeft + el.clientWidth - gutter
    el.scrollTop = top
    if (!inView) el.scrollLeft = Math.max(0, x - 16 * scale)
    setView({ top: el.scrollTop, left: el.scrollLeft, w: el.clientWidth, h: el.clientHeight })
  }

  const pick = (f: typeof find) => (f?.matches.length ? f.matches[((f.step % f.matches.length) + f.matches.length) % f.matches.length] : null)
  const current = pick(find)
  const matchSet = useMemo(() => new Set(find?.matches.map(([r, c]) => `${r}:${c}`)), [find])

  useImperativeHandle(ref, () => ({
    navigateTo(location: SourceLocation, regionIndex = 0) {
      const regions = csvRegions(location)
      const r = regions[regionIndex] ?? regions[0]
      if (r) scrollToCell(r.row_start, r.col_start)
    },
    highlight: (hs: Highlight[]) => setHl(hs),
    clearHighlights: () => setHl([]),
    search(query: string, previous = false) {
      if (!table) return
      const same = find?.query === query
      const next = {
        query,
        step: same ? find.step + (previous ? -1 : 1) : previous ? -1 : 0,
        matches: same ? find.matches : findCells(table, query),
      }
      setFind(next)
      const at = pick(next)
      if (at) scrollToCell(at[0], at[1])
    },
    goToPage() {},
    zoom(action) {
      const el = containerRef.current
      if (action === 'fit-width' || action === 'fit-page') {
        const full = (base?.gutter ?? 48) + (base?.total ?? 0)
        setScale(el && full ? Math.min(1, Math.max(MIN_SCALE, (el.clientWidth - 2) / full)) : 1)
        return
      }
      setScale((s) => (action === 'in' ? Math.min(MAX_SCALE, s * 1.1) : Math.max(MIN_SCALE, s / 1.1)))
    },
  }))

  const marks = useMemo(
    () => hl.flatMap((h) => csvRegions(h.location).map((r) => ({ ...r, low: !!h.lowConfidence }))),
    [hl],
  )
  const pins = useMemo(() => {
    const out = new Map<number, { label: string; low: boolean }>()
    for (const h of hl) {
      const r = csvRegions(h.location)[0]
      if (r && h.label && !out.has(r.row_start)) out.set(r.row_start, { label: h.label, low: !!h.lowConfidence })
    }
    return out
  }, [hl])

  if (!table || !base) return <div ref={containerRef} className="ad-viewer absolute inset-0" />

  const firstCol = colAt(lefts, Math.max(0, view.left - gutter))
  const lastCol = colAt(lefts, view.left + view.w)
  const cols: number[] = []
  for (let c = Math.max(0, firstCol - 1); c <= Math.min(table.columns.length - 1, lastCol + 1); c++) cols.push(c)
  const first = Math.max(0, Math.floor(view.top / rowH) - 1 - OVERSCAN)
  const last = Math.min(bodyCount - 1, Math.ceil((view.top + view.h) / rowH) + OVERSCAN)
  const rows: number[] = []
  for (let i = first; i <= last; i++) rows.push(i)

  const cellState = (row: number, col: number) => {
    const m = marks.find((r) => row >= r.row_start && row <= r.row_end && col >= r.col_start && col <= r.col_end)
    const isCurrent = current?.[0] === row && current[1] === col
    const isFind = !isCurrent && matchSet.has(`${row}:${col}`)
    return {
      'data-hit': m ? (m.low ? 'low' : 'evidence') : undefined,
      'data-find': isCurrent ? 'current' : isFind ? 'match' : undefined,
    }
  }
  const gutterCell = (row: number | null) => {
    const pin = row !== null ? pins.get(row) : undefined
    return (
      <div className="ad-csv-gutter" role="rowheader" style={{ width: gutter }}>
        {pin ? (
          <span className="ad-pin ad-csv-pin" data-low={String(pin.low)}>
            {pin.label}
          </span>
        ) : (
          (row ?? '')
        )}
      </div>
    )
  }
  const cell = (row: number, c: number, raw: string, role: 'gridcell' | 'columnheader') => {
    const text = cellText(raw)
    return (
      <div
        key={c}
        role={role}
        aria-colindex={c + 1}
        className="ad-csv-cell"
        data-num={base.numeric[c] && role === 'gridcell' ? 'true' : undefined}
        title={text.length > 30 ? text : undefined}
        style={{ left: gutter + lefts[c], width: base.widths[c] * scale }}
        {...cellState(row, c)}
      >
        {text}
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="ad-viewer ad-csv absolute inset-0 overflow-auto"
      tabIndex={0}
      aria-label="Document"
      onScroll={(e) => {
        const el = e.currentTarget
        setView({ top: el.scrollTop, left: el.scrollLeft, w: el.clientWidth, h: el.clientHeight })
      }}
      style={{ '--ad-scale': scale, '--ad-row': `${rowH}px` } as CSSProperties}
    >
      <div
        role="grid"
        aria-label={`${table.columns.length} columns, ${table.rows.length} rows`}
        aria-rowcount={bodyCount + 1}
        aria-colcount={table.columns.length}
        className="ad-csv-grid"
        style={{ width, height: rowH * (bodyCount + 1) }}
      >
        <div role="row" aria-rowindex={1} className="ad-csv-head" style={{ width, height: rowH }} data-header={String(hi !== null)}>
          {gutterCell(hi !== null ? hi + 1 : null)}
          {cols.map((c) => cell(hi !== null ? hi + 1 : 0, c, table.columns[c], 'columnheader'))}
        </div>
        {rows.map((i) => {
          const row = recordAt(i) + 1
          const cells = table.rows[recordAt(i)]
          return (
            <div
              key={row}
              role="row"
              aria-rowindex={i + 2}
              className="ad-csv-row"
              style={{ top: rowH * (i + 1), width, height: rowH }}
            >
              {gutterCell(row)}
              {cols.map((c) => cell(row, c, cells[c] ?? '', 'gridcell'))}
            </div>
          )
        })}
      </div>
    </div>
  )
}
