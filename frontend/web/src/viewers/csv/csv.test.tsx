import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Citation, CsvLocation, DocumentOut } from '../../lib/api'
import { useUi } from '../../stores/ui'
import type { ViewerHandle } from '../core/contract'
import { DocumentViewer } from '../core/DocumentViewer'
import { adapters } from '../core/registry'
import { columnLetter, MalformedCsv, parse, readTable, sniff } from './csv'
import CsvViewer from './CsvViewer'

// Written by `uv run python -m backend.tests.csvgen` from the backend's own parser.
const FIXTURES = resolve(__dirname, 'fixtures')
type Expected = { encoding: string; delimiter: string; headerIndex: number | null; columns: string[]; rows: string[][] }
const EXPECTED: Record<string, Expected> = JSON.parse(readFileSync(resolve(FIXTURES, 'expected.json'), 'utf8'))
const bytes = (name: string) => {
  const b = readFileSync(resolve(FIXTURES, name))
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer
}

describe('csv parsing mirrors the backend', () => {
  it.each(Object.keys(EXPECTED))('%s: same encoding, delimiter, header, column names and cells', (name) => {
    const t = readTable(bytes(name))
    const want = EXPECTED[name]
    expect({ encoding: t.encoding, delimiter: t.delimiter, headerIndex: t.headerIndex, columns: t.columns, rows: t.rows }).toEqual(want)
  })

  it.each([
    ['"ab"c,d\n', [['abc', 'd']]],
    ['a"b"c,d\n', [['a"b"c', 'd']]],
    ['\n\na,b\n', [[], [], ['a', 'b']]],
    ['""\n', [['']]],
    ['a,b,', [['a', 'b', '']]],
    ['', []],
  ])('parse(%j)', (text, rows) => {
    expect(parse(text, ',')).toEqual(rows)
  })

  it('fails on a quote that is never closed, but a cut-off sample just ends', () => {
    expect(() => parse('a,b\n"open,1\n2,3\n', ',')).toThrow(MalformedCsv)
    expect(parse('a,b\n"open,1\n', ',', true)).toEqual([['a', 'b']])
  })

  it('ignores a record cut by the sniff window, counted in code points', () => {
    expect(sniff('a,b,c\n' + '1,2,3\n'.repeat(20_000))).toBe(',')
    expect(sniff('😀;x\n'.repeat(30_000))).toBe(';')
  })

  it('names columns like a spreadsheet', () => {
    expect([0, 25, 26, 27, 701, 702].map(columnLetter)).toEqual(['A', 'Z', 'AA', 'AB', 'ZZ', 'AAA'])
  })
})

let scroll: { top: number; left: number }
beforeEach(() => {
  scroll = { top: 0, left: 0 }
  // jsdom has no layout: give the viewer a 600 x 800 viewport that remembers scroll positions.
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(600)
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800)
  Object.defineProperty(HTMLElement.prototype, 'scrollTop', {
    configurable: true,
    get: () => scroll.top,
    set: (v: number) => (scroll.top = v),
  })
  Object.defineProperty(HTMLElement.prototype, 'scrollLeft', {
    configurable: true,
    get: () => scroll.left,
    set: (v: number) => (scroll.left = v),
  })
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  vi.stubGlobal('fetch', vi.fn(async () => new Response(bytes('orders.csv'), { status: 200 })))
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  delete (HTMLElement.prototype as Partial<HTMLElement>).scrollTop
  delete (HTMLElement.prototype as Partial<HTMLElement>).scrollLeft
  document.body.replaceChildren()
})

const loc = (row_start: number, row_end: number, col_start: number, col_end: number, rows = row_end - row_start + 1): CsvLocation => ({
  kind: 'csv',
  regions: [{ row_start, row_end, col_start, col_end }],
  rows,
  columns: [],
})
const rowOf = (c: HTMLElement, n: number) => c.querySelector<HTMLElement>(`[role=row][aria-rowindex="${n}"]`)

async function mount() {
  const ref = createRef<ViewerHandle>()
  const onState = vi.fn()
  const view = render(<CsvViewer src="/f" format="csv" ref={ref} onState={onState} />)
  await waitFor(() => expect(onState).toHaveBeenCalledWith({ status: 'ready', scale: 1 }))
  return { ...view, ref, onState }
}

describe('CsvViewer', () => {
  it('is registered for the backend format "csv"', () => {
    expect(adapters.csv).toBeDefined()
  })

  it('renders the header row and only the rows in view', async () => {
    const { container } = await mount()
    const head = rowOf(container, 1)!
    expect(head.querySelector('[role=rowheader]')).toHaveTextContent('1')
    expect([...head.querySelectorAll('[role=columnheader]')].map((c) => c.textContent).slice(0, 3)).toEqual(['Order ID', 'Date', 'Region'])
    expect(rowOf(container, 2)).toHaveTextContent('LB-1001')
    const rendered = container.querySelectorAll('[role=row]').length
    expect(rendered).toBeGreaterThan(10)
    expect(rendered).toBeLessThan(60) // 121 records in the file
    expect(rowOf(container, 121)).toBeNull()
    // Number columns are right-aligned; text columns are not.
    const cells = rowOf(container, 2)!.querySelectorAll<HTMLElement>('[role=gridcell]')
    expect(cells[6].dataset.num).toBe('true')
    expect(cells[2].dataset.num).toBeUndefined()
  })

  it('pins a header found below title lines and shows the title lines first, in file order', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(bytes('title-rows.csv'), { status: 200 })))
    const { container } = await mount()
    const head = rowOf(container, 1)!
    expect(head.querySelector('[role=rowheader]')).toHaveTextContent('4')
    expect([...head.querySelectorAll('[role=columnheader]')].map((c) => c.textContent)).toEqual(['Column A', 'Version', 'Date', 'Notes'])
    const body = [...container.querySelectorAll<HTMLElement>('.ad-csv-row')]
    expect(body.map((r) => r.querySelector('[role=rowheader]')!.textContent)).toEqual(['1', '2', '3', '5', '6'])
    expect(body[0]).toHaveTextContent('Report title line two')
    expect(body.map((r) => r.style.top)).toEqual(['28px', '56px', '84px', '112px', '140px'])
    expect(body[4].querySelectorAll('[role=gridcell]')[1]).toHaveTextContent('3.9-3.93')
  })

  it('a citation washes exactly its cells, pins the row and scrolls it into view', async () => {
    const { container, ref } = await mount()
    act(() => {
      ref.current!.highlight([{ location: loc(100, 101, 7, 8), label: '2' }])
      ref.current!.navigateTo(loc(100, 101, 7, 8))
    })
    await waitFor(() => expect(rowOf(container, 100)).not.toBeNull())
    expect(scroll.top).toBeGreaterThan(0)
    const hits = [...container.querySelectorAll<HTMLElement>('[data-hit=evidence]')]
    expect(hits).toHaveLength(4)
    expect(hits.every((h) => ['7', '8', '9'].includes(h.getAttribute('aria-colindex')!))).toBe(true)
    expect(rowOf(container, 100)!.querySelector('.ad-csv-pin')).toHaveTextContent('2')
    expect(rowOf(container, 101)!.querySelector('.ad-csv-pin')).toBeNull()
    act(() => ref.current!.clearHighlights())
    expect(container.querySelector('[data-hit]')).toBeNull()
  })

  it('header cells can be evidence too', async () => {
    const { container, ref } = await mount()
    act(() => ref.current!.highlight([{ location: loc(1, 1, 2, 2), label: '1' }]))
    expect(rowOf(container, 1)!.querySelector('[data-hit=evidence]')).toHaveTextContent('Region')
  })

  it('steps through regions of a multi-region citation', async () => {
    const { container, ref } = await mount()
    const two: CsvLocation = { kind: 'csv', regions: [{ row_start: 5, row_end: 5, col_start: 0, col_end: 0 }, { row_start: 110, row_end: 110, col_start: 0, col_end: 0 }], rows: 2 }
    act(() => ref.current!.navigateTo(two, 1))
    await waitFor(() => expect(rowOf(container, 110)).not.toBeNull())
  })

  it('find marks every match and scrolls to the current one', async () => {
    const { container, ref } = await mount()
    act(() => ref.current!.search('warranty'))
    await waitFor(() => expect(container.querySelector('[data-find=current]')).toHaveTextContent('Replaced under warranty'))
    expect(container.querySelector('[data-find=current]')!.closest('[role=row]')!.getAttribute('aria-rowindex')).toBe('50')
    act(() => ref.current!.search('Bayfront'))
    await waitFor(() => expect(container.querySelector('[data-find=current]')).toHaveTextContent('Bayfront'))
    expect(container.querySelectorAll('[data-find=match]').length).toBeGreaterThan(0)
  })

  it('zooms and fits the table width', async () => {
    const { ref, onState } = await mount()
    act(() => ref.current!.zoom('in'))
    await waitFor(() => expect(onState).toHaveBeenLastCalledWith({ status: 'ready', scale: 1.1 }))
    act(() => ref.current!.zoom('fit-width'))
    await waitFor(() => expect(onState.mock.lastCall![0].scale).toBeLessThanOrEqual(1))
  })

  it('shows a readable error for a broken file', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('a,b\n"never closed\n', { status: 200 })))
    const onState = vi.fn()
    render(<CsvViewer src="/f" format="csv" ref={createRef()} onState={onState} />)
    await waitFor(() => expect(onState).toHaveBeenLastCalledWith({ status: 'error', message: 'A quoted value in row 2 is never closed.' }))
  })
})

const csvDoc: DocumentOut = {
  id: 'd3',
  title: 'lumen-orders',
  filename: 'lumen-orders.csv',
  format: 'csv',
  size_bytes: 1,
  page_count: null,
  extent: '120 rows, 11 columns',
  version: 1,
  status: 'ready',
  progress: 1,
  stage_detail: null,
  error: null,
  file_url: '/api/documents/d3/file',
  created_at: '2026-11-28T00:00:00Z',
}
const citation: Citation = {
  block_id: 'csvq:0:aa',
  quote: 'sum of "Units" = 302',
  page: null,
  ref: '47 rows, Region and Units',
  location: { kind: 'csv', regions: [{ row_start: 2, row_end: 2, col_start: 2, col_end: 2 }, { row_start: 2, row_end: 2, col_start: 6, col_end: 6 }, { row_start: 5, row_end: 5, col_start: 2, col_end: 2 }], rows: 47, columns: ['Region', 'Units'] },
  match: 'exact',
  score: 100,
  flags: [],
}

describe('citation click-through (csv)', () => {
  it('activating a citation washes the cells it read and shows the region stepper', async () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <DocumentViewer doc={csvDoc} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(rowOf(container, 2)).not.toBeNull())
    act(() => useUi.getState().activate('m1:1', 1, citation))
    await waitFor(() => expect(container.querySelectorAll('[data-hit=evidence]')).toHaveLength(3))
    expect(rowOf(container, 2)!.querySelector('.ad-csv-pin')).toHaveTextContent('1')
    expect(screen.getByLabelText('Evidence locations')).toHaveTextContent('1 of 3')
    expect(screen.queryByLabelText('Page number')).toBeNull()
  })
})
