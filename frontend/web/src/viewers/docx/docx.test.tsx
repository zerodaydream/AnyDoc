import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { renderAsync } from 'docx-preview'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createRef } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Citation, DocumentOut, DocxLocation } from '../../lib/api'
import { useUi } from '../../stores/ui'
import type { ViewerHandle } from '../core/contract'
import { DocumentViewer } from '../core/DocumentViewer'
import { adapters } from '../core/registry'
import { paragraphAnchors, paragraphText, rangeForOffsets, RENDER_OPTIONS, sanitise } from './docx'
import DocxViewer from './DocxViewer'

// Written by `uv run python -m backend.tests.docxgen` from the same sample the backend tests use.
const FIXTURES = resolve(__dirname, 'fixtures')
const SAMPLE = readFileSync(resolve(FIXTURES, 'sample.docx'))
const PARAS: string[] = JSON.parse(readFileSync(resolve(FIXTURES, 'sample.paragraphs.json'), 'utf8'))
const sampleBuffer = () => SAMPLE.buffer.slice(SAMPLE.byteOffset, SAMPLE.byteOffset + SAMPLE.byteLength) as ArrayBuffer

async function renderSample(): Promise<HTMLElement> {
  const host = document.createElement('div')
  const styles = document.createElement('div')
  document.body.append(styles, host)
  await renderAsync(sampleBuffer(), host, styles, RENDER_OPTIONS)
  return host
}

const stubFetch = () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(sampleBuffer(), { status: 200 })))
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} }) // not in jsdom
}

const at = (text: string) => PARAS.findIndex((p) => p.startsWith(text))

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.replaceChildren()
})

describe('docx paragraph order mirrors the backend', () => {
  it('renders every paragraph the backend counts, in the same order, with the same text', async () => {
    const host = await renderSample()
    const anchors = paragraphAnchors(host)
    expect(anchors.map(paragraphText)).toEqual(PARAS)
  })

  it('maps code-point offsets to the exact rendered text, across tabs and line breaks', async () => {
    const host = await renderSample()
    const i = at('Planned maintenance windows:')
    const p = paragraphAnchors(host)[i]
    const quote = 'announced 7 days ahead'
    const start = PARAS[i].indexOf(quote)
    expect(rangeForOffsets(p, start, start + quote.length)?.toString()).toBe(quote)
    const tabbed = PARAS[i].indexOf('Sundays')
    expect(rangeForOffsets(p, tabbed, tabbed + 7)?.toString()).toBe('Sundays')
    expect(rangeForOffsets(p, 0, 10_000)).toBeNull() // offsets that don't fit -> paragraph wash only
  })
})

describe('docx sanitising', () => {
  it('keeps only safe links, package images and no embedded objects', () => {
    const root = document.createElement('div')
    root.innerHTML =
      '<a href="javascript:alert(1)">x</a><a href="mailto:a@b.example">m</a><a href="#_Toc1">t</a>' +
      '<img src="https://tracker.example/p.gif"><img src="blob:http://localhost/1"><iframe srcdoc="hi"></iframe>' +
      '<span onclick="alert(1)">s</span>'
    sanitise(root)
    const [js, mail, toc] = root.querySelectorAll('a')
    expect(js).not.toHaveAttribute('href')
    expect(mail).toHaveAttribute('href', 'mailto:a@b.example')
    expect(mail).toHaveAttribute('rel', 'noopener noreferrer nofollow')
    expect(toc).not.toHaveAttribute('href')
    const [remote, local] = root.querySelectorAll('img')
    expect(remote).not.toHaveAttribute('src')
    expect(local).toHaveAttribute('src', 'blob:http://localhost/1')
    expect(root.querySelector('iframe')).toBeNull()
    expect(root.querySelector('span')).not.toHaveAttribute('onclick')
  })

  it('the sample renders its mailto link as a safe external link', async () => {
    const host = await renderSample()
    sanitise(host)
    expect(host.querySelector('a[href^="mailto:"]')).toHaveAttribute('target', '_blank')
  })
})

const feeIdx = at('Harbor Lane Logistics will pay')
const feeQuote = 'fixed monthly fee of EUR 18,500'
const feeStart = PARAS[feeIdx].indexOf(feeQuote)
const location: DocxLocation = {
  kind: 'docx',
  regions: [{ para: feeIdx, char_start: feeStart, char_end: feeStart + feeQuote.length }],
  paragraph_start: 15,
  paragraph_end: 15,
}

describe('DocxViewer', () => {
  it('is registered for docx', () => {
    expect(adapters.docx).toBeTruthy()
  })

  it('washes cited paragraphs (one per table cell), pins the first, and clears', async () => {
    stubFetch()
    const ref = createRef<ViewerHandle>()
    const onState = vi.fn()
    const { container } = render(<DocxViewer src="/f" format="docx" ref={ref} onState={onState} />)
    await waitFor(() => expect(onState).toHaveBeenCalledWith(expect.objectContaining({ status: 'ready' })), { timeout: 5000 })
    const cells: DocxLocation = {
      kind: 'docx',
      regions: ['Critical', '15 minutes', '4 hours'].map((t) => ({ para: at(t), char_start: 0, char_end: t.length })),
      table: 1,
      row_start: 2,
      row_end: 2,
    }
    act(() => ref.current!.highlight([{ location, label: '1' }, { location: cells, label: '2', lowConfidence: true }]))
    const hits = [...container.querySelectorAll('.ad-docx-hit')].map((p) => p.textContent)
    expect(hits).toEqual(['Critical', '15 minutes', '4 hours', PARAS[feeIdx]]) // document order
    expect(container.querySelectorAll('.ad-docx-hit[data-low="true"]')).toHaveLength(3)
    expect([...container.querySelectorAll('.ad-docx-pin')].map((p) => p.textContent)).toEqual(['1', '2'])
    act(() => ref.current!.navigateTo(location))
    act(() => ref.current!.clearHighlights())
    expect(container.querySelector('.ad-docx-hit')).toBeNull()
    expect(container.querySelector('.ad-docx-pin')).toBeNull()
  })

  it('shows a readable error when the file cannot be loaded', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 404 })))
    const onState = vi.fn()
    render(<DocxViewer src="/f" format="docx" ref={createRef()} onState={onState} />)
    await waitFor(() => expect(onState).toHaveBeenCalledWith({ status: 'error', message: 'The file could not be loaded (404).' }))
  })
})

const docxDoc: DocumentOut = {
  id: 'd2',
  title: 'Master Services Agreement',
  filename: 'msa.docx',
  format: 'docx',
  size_bytes: SAMPLE.byteLength,
  page_count: null,
  extent: '284 words',
  version: 1,
  status: 'ready',
  progress: 1,
  stage_detail: null,
  error: null,
  file_url: '/api/documents/d2/file',
  created_at: '2026-11-27T00:00:00Z',
}
const citation: Citation = {
  block_id: `docx:${feeIdx}:14:aa`,
  quote: feeQuote,
  page: null,
  ref: 'paragraph 15',
  location,
  match: 'exact',
  score: 100,
  flags: [],
}

describe('citation click-through (docx)', () => {
  it('activating a citation washes and pins the cited paragraph', async () => {
    stubFetch()
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <DocumentViewer doc={docxDoc} />
      </QueryClientProvider>,
    )
    await screen.findByLabelText('Document')
    await waitFor(() => expect(container.querySelector('section.docx')).not.toBeNull(), { timeout: 5000 })
    act(() => useUi.getState().activate('m1:1', 1, citation))
    await waitFor(() => expect(container.querySelector('.ad-docx-hit')).toHaveTextContent('EUR 18,500'))
    expect(container.querySelector('.ad-docx-pin')).toHaveTextContent('1')
    expect(screen.queryByLabelText('Page number')).toBeNull()
  })
})
