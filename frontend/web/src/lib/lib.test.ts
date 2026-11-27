import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { applyEvent, numbered, startAnswer } from '../features/chat/answerReducer'
import { adapters } from '../viewers/core/registry'
import { toCssBox } from '../viewers/pdf/geometry'
import type { Citation } from './api'
import { createSseParser } from './sse'

const cite = (page: number): Citation => ({
  block_id: `pdf:${page}:0:aa`,
  quote: 'q',
  page,
  location: { kind: 'pdf', regions: [{ page, rects: [[72, 660, 300, 690]] }] },
  match: 'exact',
  score: 100,
  flags: [],
})

describe('sse parser', () => {
  it('reassembles frames split across chunks', () => {
    const parse = createSseParser()
    expect(parse('event: meta\ndata: {"a"')).toEqual([])
    expect(parse(':1}\n\nevent: done\r\ndata: {"status":"answered"}\r\n\r\n')).toEqual([
      { event: 'meta', data: { a: 1 } },
      { event: 'done', data: { status: 'answered' } },
    ])
  })
})

describe('answer reducer', () => {
  it('streams text, attaches citations, retracts segments', () => {
    const events = [
      { event: 'meta', data: { message_id: 'm1' } },
      { event: 'text_delta', data: { segment: 0, text: 'Revenue ' } },
      { event: 'text_delta', data: { segment: 0, text: 'was $4.2M.' } },
      { event: 'text_delta', data: { segment: 1, text: 'Made up.' } },
      { event: 'citation', data: { segment: 0, index: 0, citation: cite(1) } },
      { event: 'segment_retracted', data: { segment: 1, reason: 'no_valid_evidence' } },
      { event: 'done', data: { status: 'partial', closest: [] } },
    ]
    const a = events.reduce(applyEvent, startAnswer('q'))
    expect(a.id).toBe('m1')
    expect(a.segments[0]).toEqual({ text: 'Revenue was $4.2M.', citations: [cite(1)] })
    expect(a.segments[1].retracted).toBe('no_valid_evidence')
    expect(a.status).toBe('partial')
  })

  it('numbers citations across segments', () => {
    const n = numbered([
      { text: 'a', citations: [cite(1), cite(2)] },
      { text: 'b', citations: [cite(3)] },
    ])
    expect(n.flatMap((s) => s.numbered.map((x) => x.n))).toEqual([1, 2, 3])
  })

  it('surfaces errors', () => {
    const a = applyEvent(startAnswer('q'), { event: 'error', data: { code: 'llm_unavailable', message: 'down' } })
    expect(a.status).toBe('error')
    expect(a.error).toBe('down')
  })
})

describe('pdf geometry', () => {
  it('normalises flipped viewport rects into a CSS box', () => {
    // pdf.js at rotation 0 flips y: (x, y) -> (x*s, (H - y)*s). Page height 792, scale 2.
    const viewport = { convertToViewportPoint: (x: number, y: number) => [x * 2, (792 - y) * 2] }
    expect(toCssBox(viewport, [72, 660, 300, 690], 0)).toEqual({ left: 144, top: 204, width: 456, height: 60 })
  })

  it('handles 90-degree rotation (x and y swap)', () => {
    // rotation 90 at scale 1: (x, y) -> (y, x) for an unshifted page
    const viewport = { convertToViewportPoint: (x: number, y: number) => [y, x] }
    expect(toCssBox(viewport, [72, 660, 300, 690], 0)).toEqual({ left: 660, top: 72, width: 30, height: 228 })
  })
})

describe('viewer registry', () => {
  it('selects by validated format only', () => {
    expect(adapters.pdf).toBeTruthy()
    expect(adapters['pptx']).toBeUndefined()
  })
})

describe('design tokens', () => {
  const css = readFileSync('src/index.css', 'utf8')
  const block = (sel: string) => css.slice(css.indexOf(sel), css.indexOf('}', css.indexOf(sel)))
  const token = (b: string, name: string) => b.match(new RegExp(`--${name}: (#[0-9a-f]{6})`))![1]
  const lum = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map((i) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
    })
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const ratio = (a: string, b: string) => {
    const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m)
    return (x + 0.05) / (y + 0.05)
  }

  it.each(["[data-theme='dark']", "[data-theme='light']"])('%s meets WCAG AA', (sel) => {
    const b = block(sel)
    for (const bg of ['bg', 'surface']) {
      expect(ratio(token(b, 'text'), token(b, bg))).toBeGreaterThanOrEqual(4.5)
      expect(ratio(token(b, 'text-muted'), token(b, bg))).toBeGreaterThanOrEqual(4.5)
      expect(ratio(token(b, 'accent'), token(b, bg))).toBeGreaterThanOrEqual(3) // large/UI text
    }
    expect(ratio(token(b, 'on-accent'), token(b, 'accent'))).toBeGreaterThanOrEqual(4.5)
  })
})

describe('answer reducer reset', () => {
  it('drops partial text when the server restarts the stream', () => {
    let a = applyEvent(startAnswer('q'), { event: 'text_delta', data: { segment: 0, text: 'Partial' } })
    a = applyEvent(a, { event: 'reset', data: {} })
    expect(a.segments).toEqual([])
    expect(a.status).toBe('streaming')
  })
})
