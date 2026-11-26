/**
 * Text viewer model. Decoding mirrors backend/extraction/formats/text/decode.py exactly, so the string
 * here is the string the backend cut blocks from. Backend offsets count code points; JS strings index
 * UTF-16 units, so offsets are converted once (identity when the text has no astral characters).
 */

export type Decoded = { text: string; encoding: string }

const BOMS: [number[], string][] = [
  [[0xef, 0xbb, 0xbf], 'utf-8'],
  [[0xff, 0xfe], 'utf-16le'],
  [[0xfe, 0xff], 'utf-16be'],
]

export function decodeText(buf: ArrayBuffer): Decoded {
  const bytes = new Uint8Array(buf)
  const bom = BOMS.find(([b]) => b.every((v, i) => bytes[i] === v))
  let text: string
  let encoding: string
  if (bom) {
    encoding = bom[1]
    text = new TextDecoder(encoding, { fatal: true }).decode(bytes) // strips the BOM
  } else {
    try {
      encoding = 'utf-8'
      text = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    } catch {
      encoding = 'windows-1252'
      text = new TextDecoder('windows-1252').decode(bytes)
    }
  }
  return { text: text.replace(/\r\n?/g, '\n'), encoding }
}

/** Code-point offset -> UTF-16 index. */
export function codePointIndex(text: string): (cp: number) => number {
  if (!/[\uD800-\uDFFF]/.test(text)) return (cp) => cp
  const units: number[] = []
  for (let i = 0; i < text.length; i++) {
    units.push(i)
    const c = text.charCodeAt(i)
    if (c >= 0xd800 && c <= 0xdbff && i + 1 < text.length) i++
  }
  units.push(text.length)
  return (cp) => units[Math.min(Math.max(cp, 0), units.length - 1)]
}

/** UTF-16 index where each line starts (only "\n" ends a line, as in the backend). */
export function lineStarts(text: string): number[] {
  const starts = [0]
  for (let i = text.indexOf('\n'); i !== -1; i = text.indexOf('\n', i + 1)) starts.push(i + 1)
  return starts
}

/** Index of the line containing UTF-16 offset `at`. */
export function lineOf(starts: number[], at: number): number {
  let lo = 0
  let hi = starts.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (starts[mid] <= at) lo = mid
    else hi = mid - 1
  }
  return lo
}

export type MarkKind = 'evidence' | 'low' | 'find' | 'find-current'
export type Mark = { start: number; end: number; kind: MarkKind; label?: string } // UTF-16, end exclusive
export type LineMark = { start: number; end: number; kind: MarkKind; label?: string } // relative to the line

/** Split document-level marks into per-line pieces. The label (margin note) goes on the first piece only. */
export function marksByLine(text: string, starts: number[], marks: Mark[]): Map<number, LineMark[]> {
  const out = new Map<number, LineMark[]>()
  for (const m of marks) {
    if (m.end <= m.start) continue
    for (let ln = lineOf(starts, m.start); ln < starts.length && starts[ln] < m.end; ln++) {
      const ls = starts[ln]
      const le = ln + 1 < starts.length ? starts[ln + 1] - 1 : text.length
      const s = Math.max(m.start, ls) - ls
      const e = Math.min(m.end, le) - ls
      if (e <= s) continue // blank line inside a multi-line span: nothing to paint
      const list = out.get(ln) ?? []
      list.push({ start: s, end: e, kind: m.kind, label: ln === lineOf(starts, m.start) ? m.label : undefined })
      out.set(ln, list)
    }
  }
  return out
}

export type Piece = { text: string; kinds: MarkKind[] }

/** Cut one line into runs that share the same set of marks (marks may overlap). */
export function pieces(line: string, marks: LineMark[] = []): Piece[] {
  if (!marks.length) return [{ text: line, kinds: [] }]
  const cuts = new Set([0, line.length])
  for (const m of marks) {
    cuts.add(Math.min(m.start, line.length))
    cuts.add(Math.min(m.end, line.length))
  }
  const sorted = [...cuts].sort((a, b) => a - b)
  const out: Piece[] = []
  for (let i = 0; i + 1 < sorted.length; i++) {
    const [a, b] = [sorted[i], sorted[i + 1]]
    if (a === b) continue
    out.push({ text: line.slice(a, b), kinds: marks.filter((m) => m.start <= a && m.end >= b).map((m) => m.kind) })
  }
  return out
}

export type LineKind = 'h1' | 'h2' | 'h3' | 'code' | 'quote' | 'table' | 'meta' | null

/** Cosmetic Markdown line styling. Never changes the text, so offsets are untouched. */
/** YAML front matter at the very top -> number of lines it spans, else 0 (same rule as the backend). */
export function frontMatterEnd(lines: string[]): number {
  if (lines[0]?.trim() !== '---') return 0
  const close = lines.findIndex((l, k) => k > 0 && k < 500 && (l.trim() === '---' || l.trim() === '...'))
  return close > 0 ? close + 1 : 0
}

export function markdownLineKinds(lines: string[]): LineKind[] {
  const kinds: LineKind[] = lines.map(() => null)
  let i = 0
  for (const fm = frontMatterEnd(lines); i < fm; i++) kinds[i] = 'meta'
  let fence: string | null = null
  for (; i < lines.length; i++) {
    const line = lines[i]
    if (fence) {
      kinds[i] = 'code'
      if (line.trim().startsWith(fence)) fence = null
      continue
    }
    const open = /^\s{0,3}(`{3,}|~{3,})/.exec(line)
    if (open) {
      fence = open[1]
      kinds[i] = 'code'
      continue
    }
    const atx = /^\s{0,3}(#{1,6})(\s|$)/.exec(line)
    if (atx) {
      kinds[i] = (['h1', 'h2', 'h3'] as const)[Math.min(atx[1].length, 3) - 1]
      continue
    }
    const next = lines[i + 1]
    if (line.trim() && next !== undefined && /^\s{0,3}(=+|-+)\s*$/.test(next) && !/^\s*([-*+]|\d+\.)\s/.test(line)) {
      kinds[i] = next.includes('=') ? 'h1' : 'h2'
      kinds[i + 1] = 'meta'
      i++
      continue
    }
    if (/^\s{0,3}>/.test(line)) kinds[i] = 'quote'
    else if (/^\s*\|/.test(line)) kinds[i] = 'table'
  }
  return kinds
}

/** Case-insensitive match starts (UTF-16). Capped so a one-letter query can't stall the page. */
export function findAll(text: string, query: string, cap = 5000): number[] {
  const q = query.toLowerCase()
  if (!q) return []
  const hay = text.toLowerCase()
  if (hay.length !== text.length) return [] // shortcut: rare case-folding length changes; find is disabled there
  const out: number[] = []
  for (let i = hay.indexOf(q); i !== -1 && out.length < cap; i = hay.indexOf(q, i + q.length)) out.push(i)
  return out
}
