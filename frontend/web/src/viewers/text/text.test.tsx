import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { createRef } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Citation, DocumentOut, TextLocation } from '../../lib/api'
import { useUi } from '../../stores/ui'
import type { ViewerHandle } from '../core/contract'
import { DocumentViewer } from '../core/DocumentViewer'
import { adapters } from '../core/registry'
import { codePointIndex, decodeText, findAll, lineStarts, markdownLineKinds, marksByLine, pieces } from './text'
import { blocksForLines, rangeForQuote, renderMarkdown, washTargets } from './preview'
import TextViewer from './TextViewer'

const bytes = (...xs: number[]) => new Uint8Array(xs).buffer
const utf8 = (s: string) => new TextEncoder().encode(s).buffer as ArrayBuffer

describe('text decoding mirrors the backend', () => {
  // Same fixtures as backend/tests/test_text_extraction.py::test_decode
  it.each([
    [utf8('plain\r\nwindows\rold mac\n'), 'plain\nwindows\nold mac\n', 'utf-8'],
    [bytes(0xef, 0xbb, 0xbf, 0x62, 0x6f, 0x6d, 0x20, 0x63, 0x61, 0x66, 0xc3, 0xa9), 'bom café', 'utf-8'],
    [bytes(0xff, 0xfe, 0x77, 0x00, 0xe9, 0x00, 0x3d, 0xd8, 0x00, 0xde), 'wé😀', 'utf-16le'],
    [bytes(0xfe, 0xff, 0x00, 0x62, 0x00, 0xe9), 'bé', 'utf-16be'],
    [bytes(0x63, 0x61, 0x66, 0xe9, 0x20, 0x93, 0x71, 0x94), 'café “q”', 'windows-1252'],
  ])('decodes %#', (buf, text, encoding) => {
    expect(decodeText(buf)).toEqual({ text, encoding })
  })

  it('maps code-point offsets to UTF-16 indices', () => {
    const t = 'a😀b☕c'
    const at = codePointIndex(t)
    expect([at(0), at(1), at(2), at(3), at(4), at(5)]).toEqual([0, 1, 3, 4, 5, 6])
    expect(t.slice(at(2), at(5))).toBe('b☕c')
    expect(codePointIndex('plain')(3)).toBe(3)
  })
})

describe('line marks', () => {
  const text = 'first line\nsecond line\n\nfourth'
  const starts = lineStarts(text)

  it('splits a multi-line mark per line and labels only the first piece', () => {
    const by = marksByLine(text, starts, [{ start: 6, end: 24, kind: 'evidence', label: '2' }])
    expect([...by.keys()]).toEqual([0, 1]) // the blank line 2 has nothing to paint
    expect(by.get(0)).toEqual([{ start: 6, end: 10, kind: 'evidence', label: '2' }])
    expect(by.get(1)).toEqual([{ start: 0, end: 11, kind: 'evidence', label: undefined }])
  })

  it('cuts overlapping marks into runs', () => {
    expect(
      pieces('abcdefgh', [
        { start: 1, end: 5, kind: 'evidence' },
        { start: 3, end: 7, kind: 'find' },
      ]),
    ).toEqual([
      { text: 'a', kinds: [] },
      { text: 'bc', kinds: ['evidence'] },
      { text: 'de', kinds: ['evidence', 'find'] },
      { text: 'fg', kinds: ['find'] },
      { text: 'h', kinds: [] },
    ])
  })

  it('styles markdown lines without touching the text', () => {
    const lines = ['---', 'title: x', '---', '# Title', 'para', '```', '# not a heading', '```', '> quote', '| a |', 'Setext', '---']
    expect(markdownLineKinds(lines)).toEqual(['meta', 'meta', 'meta', 'h1', null, 'code', 'code', 'code', 'quote', 'table', 'h2', 'meta'])
  })

  it('finds case-insensitively', () => {
    expect(findAll('Pump pump PUMP', 'pump')).toEqual([0, 5, 10])
    expect(findAll('abc', '')).toEqual([])
  })
})

const MD = '# Notes 😀\n\nThe pump runs on a 48 volt bank.\nReplace the filter every 90 days.\n'
// Code-point offsets, as the backend sends them: the emoji counts as one.
const quote = '48 volt bank.\nReplace the filter'
const cpStart = [...MD].join('').indexOf(quote) - 1
const location: TextLocation = {
  kind: 'text',
  regions: [{ char_start: cpStart, char_end: cpStart + quote.length, line_start: 3, line_end: 4 }],
}

function stubFetch(body: string) {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, arrayBuffer: async () => utf8(body), json: async () => [] })))
}

afterEach(() => vi.unstubAllGlobals())

describe('TextViewer (source view)', () => {
  beforeEach(() => localStorage.setItem('anydoc.markdownView', 'source'))
  afterEach(() => localStorage.clear())

  it('is registered for text and markdown', () => {
    expect(adapters.text).toBeTruthy()
    expect(adapters.markdown).toBe(adapters.text)
  })

  it('highlights a code-point location exactly, with a margin note, and finds text', async () => {
    stubFetch(MD)
    const ref = createRef<ViewerHandle>()
    const onState = vi.fn()
    const { container } = render(<TextViewer src="/f" format="markdown" ref={ref} onState={onState} />)
    await waitFor(() => expect(onState).toHaveBeenCalledWith(expect.objectContaining({ status: 'ready', scale: 1, mode: 'source' })))
    expect(container.querySelector('[data-line="1"]')).toHaveAttribute('data-kind', 'h1')

    act(() => ref.current!.highlight([{ location, label: '3' }]))
    const marks = [...container.querySelectorAll('mark[data-kinds="evidence"]')].map((m) => m.textContent)
    expect(marks.join('\n')).toBe(quote)
    expect(container.querySelector('[data-line="3"] .ad-pin')).toHaveTextContent('3')

    act(() => ref.current!.search('FILTER'))
    expect(container.querySelector('mark[data-kinds~="find-current"]')).toHaveTextContent('filter')
    act(() => ref.current!.clearHighlights())
    expect(container.querySelector('mark[data-kinds~="evidence"]')).toBeNull()
  })
})

const mdDoc: DocumentOut = {
      id: 'd1',
      title: 'notes',
      filename: 'notes.md',
      format: 'markdown',
      size_bytes: MD.length,
      page_count: null,
      extent: '4 lines',
      version: 1,
      status: 'ready',
      progress: 1,
      stage_detail: null,
      error: null,
      file_url: '/api/documents/d1/file',
      created_at: '2026-11-26T00:00:00Z',
}
const citation: Citation = { block_id: 'md:3:1:aa', quote, page: null, ref: 'lines 3–4', location, match: 'exact', score: 100, flags: [] }
const renderViewer = () =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <DocumentViewer doc={mdDoc} />
    </QueryClientProvider>,
  )

describe('citation click-through (text)', () => {
  afterEach(() => localStorage.clear())

  it('activating a citation highlights its lines in the source view', async () => {
    localStorage.setItem('anydoc.markdownView', 'source')
    stubFetch(MD)
    const { container } = renderViewer()
    await screen.findByLabelText('Document')
    await waitFor(() => expect(container.querySelector('[data-line="3"]')).not.toBeNull())
    act(() => useUi.getState().activate('m1:1', 1, citation))
    await waitFor(() => expect(container.querySelector('mark[data-kinds="evidence"]')).not.toBeNull())
    expect(container.querySelector('[data-line="3"] .ad-pin')).toHaveTextContent('1')
    expect(screen.queryByLabelText('Page number')).toBeNull() // no page box for formats without pages
  })
})

describe('markdown preview', () => {
  afterEach(() => localStorage.clear())

  it('renders safely and anchors every block to its source lines', () => {
    const src = [
      '---', 'title: x', '---', // 1-3
      '# Title', // 4
      '', // 5
      'Some **bold** and `code`.', // 6
      '', // 7
      '- one', '- two', // 8-9
      '', // 10
      '<script>alert(1)</script>', // 11
      '', // 12
      '![tracker](https://evil.example/p.gif) [bad](javascript:alert(1)) [ok](https://example.com) [rel](./docs/a.md)', // 13
      '', // 14
      '| a | b |', '|---|---|', '| 1 | 2 |', // 15-17
    ].join('\n')
    const el = document.createElement('div')
    el.innerHTML = renderMarkdown(src)
    expect(el.querySelector('details.ad-md-fm summary')).toHaveTextContent('Front matter · 3 lines')
    expect(el.querySelector('h1')).toHaveAttribute('data-ls', '4')
    expect(el.querySelector('strong')).toHaveTextContent('bold')
    expect(el.querySelector('script')).toBeNull() // raw HTML is shown as text, never run
    expect(el.textContent).toContain('<script>alert(1)</script>')
    expect(el.querySelector('img')).toBeNull() // images are never fetched
    expect(el.querySelector('.ad-md-img')).toHaveTextContent('tracker')
    expect([...el.querySelectorAll('a')].map((a) => a.getAttribute('href'))).toEqual(['https://example.com'])
    expect(el.querySelector('a')).toHaveAttribute('rel', 'noopener noreferrer nofollow')
    expect(el.querySelector('table')).toHaveAttribute('data-ls', '15')
    const items = blocksForLines(el, 9, 9)
    expect(items.map((b) => b.textContent)).toEqual(['two']) // innermost block only
  })

  it('finds a source quote in rendered text despite Markdown markers', () => {
    const el = document.createElement('div')
    el.innerHTML = renderMarkdown('Run **make deploy** with `ENV=prod` today.')
    document.body.appendChild(el)
    const r = rangeForQuote([el.querySelector('p')!], 'make deploy** with `ENV=prod')
    expect(r?.toString()).toBe('make deploy with ENV=prod')
    expect(rangeForQuote([el.querySelector('p')!], 'not there')).toBeNull()
    el.remove()
  })

  it('washes a cited code block as one block and still finds the quoted line', () => {
    const el = document.createElement('div')
    el.innerHTML = renderMarkdown('Tree:\n\n```\nsrc/\n  app/\n  schema/   # Runtime schema\n```\n')
    document.body.appendChild(el)
    const blocks = blocksForLines(el, 6, 6)
    expect(blocks.map((b) => b.tagName)).toEqual(['CODE'])
    expect(washTargets(blocks).map((b) => b.tagName)).toEqual(['PRE'])
    expect(rangeForQuote(blocks, 'schema/   # Runtime schema')?.toString()).toBe('schema/   # Runtime schema')
    el.remove()
  })

  it('opens in preview, washes the cited block with a pin, and toggles to source', async () => {
    stubFetch(MD)
    const { container } = renderViewer()
    await waitFor(() => expect(container.querySelector('.ad-md p')).not.toBeNull())
    expect(screen.getByRole('radio', { name: 'Preview' })).toHaveAttribute('aria-checked', 'true')

    act(() => useUi.getState().activate('m2:1', 2, citation))
    await waitFor(() => expect(container.querySelector('.ad-md-hit')).not.toBeNull())
    expect(container.querySelector('.ad-md-hit')).toHaveTextContent('The pump runs on a 48 volt bank.')
    expect(container.querySelector('.ad-md-pin')).toHaveTextContent('2')

    act(() => screen.getByRole('radio', { name: 'Markdown' }).click())
    await waitFor(() => expect(container.querySelector('.ad-sheet')).not.toBeNull())
    expect(localStorage.getItem('anydoc.markdownView')).toBe('source')
    await waitFor(() => expect(container.querySelector('mark[data-kinds="evidence"]')).not.toBeNull())
  })
})
