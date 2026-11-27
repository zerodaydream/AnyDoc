/**
 * CSV viewer model. Mirrors backend/extraction/formats/csv/table.py exactly (decoding, tokenising, delimiter,
 * header, column names), so row and column numbers here are the backend's: rows count file records from 1 (header
 * and blank lines included), columns count from 0. Parity is checked against fixtures/expected.json, written by
 * `uv run python -m backend.tests.csvgen` from the backend's own functions.
 */
import { decodeText } from '../text/text'

export const DELIMITERS = [',', '\t', ';', '|']
const SNIFF_CHARS = 65536 // code points, as Python slices
const SNIFF_RECORDS = 50
const NUMERIC = /^[-+(]?[$€£¥₹]?(?:[0-9][0-9,]*(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?%?\)?$/

export class MalformedCsv extends Error {}

/** Python's str.strip()/split() whitespace, close enough for cell text: JS \s plus the ASCII separators. */
/* eslint-disable no-control-regex -- \x1c-\x1f are whitespace to Python's str.isspace, so they must be here too */
const strip = (s: string) => s.replace(/^[\s\x1c-\x1f\x85]+|[\s\x1c-\x1f\x85]+$/g, '')
const words = (s: string) => s.split(/[\s\x1c-\x1f\x85]+/).filter(Boolean)
/* eslint-enable no-control-regex */

/** Records of `text`. `partial`: a cut-off sample, so an unclosed quote just ends it. */
export function parse(text: string, delimiter: string, partial = false): string[][] {
  const quotedRe = /"([^"]*(?:""[^"]*)*)"/y
  const unquotedRe = new RegExp(`[^${delimiter.replace(/[\\\]^-]/g, '\\$&')}\\n]*`, 'y')
  const rows: string[][] = []
  let row: string[] = []
  let i = 0
  const n = text.length
  while (i < n) {
    const quoted = text[i] === '"'
    let value = ''
    if (quoted) {
      quotedRe.lastIndex = i
      const m = quotedRe.exec(text)
      if (!m) {
        if (partial) return rows
        throw new MalformedCsv(`A quoted value in row ${(rows.length + 1).toLocaleString('en-US')} is never closed.`)
      }
      value = m[1].replaceAll('""', '"')
      i = quotedRe.lastIndex
    }
    unquotedRe.lastIndex = i
    value += unquotedRe.exec(text)![0]
    i = unquotedRe.lastIndex
    row.push(value)
    if (i < n && text[i] === delimiter) {
      i++
      if (i === n) row.push('')
      continue
    }
    rows.push(row.length === 1 && !quoted && !row[0] ? [] : row)
    row = []
    i++ // past the "\n"; a final newline adds no record
  }
  if (row.length) rows.push(row)
  return rows
}

/** First `count` code points of `text`, and whether more follow. */
function headCodePoints(text: string, count: number): [string, boolean] {
  let i = 0
  for (let cp = 0; cp < count && i < text.length; cp++) {
    const c = text.charCodeAt(i)
    i += c >= 0xd800 && c <= 0xdbff && i + 1 < text.length ? 2 : 1
  }
  return [text.slice(0, i), i < text.length]
}

export function sniff(text: string): string {
  const [sample, cut] = headCodePoints(text, SNIFF_CHARS)
  let best = ','
  let bestScore: [number, number] = [0, 0]
  for (const d of DELIMITERS) {
    let recs = parse(sample, d, true)
    if (cut) recs = recs.slice(0, -1)
    recs = recs.filter((r) => r.length).slice(0, SNIFF_RECORDS)
    if (!recs.length) continue
    const counts = new Map<number, number>()
    for (const r of recs) counts.set(r.length, (counts.get(r.length) ?? 0) + 1)
    let mode = 0
    for (const [w, c] of counts) {
      const mc = counts.get(mode) ?? 0
      if (c > mc || (c === mc && w > mode)) mode = w
    }
    if (mode < 2) continue
    const score: [number, number] = [counts.get(mode)! / recs.length, mode]
    if (score[0] > bestScore[0] || (score[0] === bestScore[0] && score[1] > bestScore[1])) {
      best = d
      bestScore = score
    }
  }
  return best
}

export function hasHeader(rows: string[][]): boolean {
  if (!rows.length || !rows[0].length) return false
  const first = rows[0].map(strip)
  const filled = first.filter(Boolean)
  if (2 * filled.length < first.length || filled.some((c) => NUMERIC.test(c))) return false
  const body = rows.slice(1, SNIFF_RECORDS + 1).filter((r) => r.length)
  if (!body.length) return false
  return !first.some((name, k) => name && body.some((r) => k < r.length && strip(r[k]) === name))
}

export function columnLetter(i: number): string {
  let s = ''
  for (let n = i + 1; n; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s
  return s
}

export function columnNames(rows: string[][], header: boolean): string[] {
  const width = rows.reduce((w, r) => Math.max(w, r.length), 0)
  const head = header ? rows[0] : []
  const seen = new Map<string, number>()
  return Array.from({ length: width }, (_, i) => {
    const base = (i < head.length ? words(head[i]).join(' ') : '') || `Column ${columnLetter(i)}`
    const n = (seen.get(base) ?? 0) + 1
    seen.set(base, n)
    return n === 1 ? base : `${base} (${n})`
  })
}

export const isNumeric = (s: string) => NUMERIC.test(strip(s))

export type Table = { rows: string[][]; header: boolean; columns: string[]; delimiter: string; encoding: string }

export function readTable(buf: ArrayBuffer): Table {
  const { text, encoding } = decodeText(buf)
  const delimiter = sniff(text)
  const rows = parse(text, delimiter)
  const header = hasHeader(rows)
  return { rows, header, columns: columnNames(rows, header), delimiter, encoding }
}

/** One line of a cell, as the grid shows it (the backend collapses whitespace the same way in its blocks). */
export const cellText = (s: string) => words(s).join(' ')
