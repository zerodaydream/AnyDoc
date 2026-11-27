import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import type { Citation } from '../../lib/api'
import { useUi } from '../../stores/ui'
import { AssistantMessage } from './AssistantMessage'

const cite: Citation = {
  block_id: 'pdf:4:2:ab',
  quote: 'Revenue for the third quarter was $4.2M',
  page: 4,
  location: { kind: 'pdf', regions: [{ page: 4, rects: [[72, 660, 300, 690]] }, { page: 5, rects: [[72, 700, 300, 720]] }] },
  match: 'exact',
  score: 100,
  flags: [],
}

describe('AssistantMessage', () => {
  beforeEach(() => useUi.setState({ active: null, mobileTab: 'chat' }))

  it('renders citations and activates the viewer on click', async () => {
    render(<AssistantMessage id="m1" status="answered" segments={[{ text: 'Q3 revenue was $4.2M.', citations: [cite] }]} />)
    await userEvent.click(screen.getByRole('button', { name: 'Citation 1, page 4' }))
    const active = useUi.getState().active
    expect(active?.key).toBe('m1:1')
    expect(active?.citation.location.regions).toHaveLength(2)
    expect(useUi.getState().mobileTab).toBe('document')
    expect(screen.getByText(/third quarter was \$4\.2M/)).toBeInTheDocument()
  })

  it('keeps the last word and its citation pills together', () => {
    const { container } = render(
      <AssistantMessage id="m5" status="answered" segments={[{ text: 'Adam was used to train it.', citations: [cite, cite] }]} />,
    )
    const run = container.querySelector('.whitespace-nowrap')!
    expect(run.textContent).toBe('it.12')
    expect(container.textContent).toContain('Adam was used to train it.12')
  })

  it('shows the suggestion under a finished answer, not while streaming', () => {
    const segs = [{ text: 'Q3 revenue was $4.2M.', citations: [cite] }]
    const { rerender } = render(<AssistantMessage id="m6" status="streaming" segments={segs} suggestion="Ask how costs changed." />)
    expect(screen.queryByText('Ask how costs changed.')).toBeNull()
    rerender(<AssistantMessage id="m6" status="answered" segments={segs} suggestion="Ask how costs changed." />)
    expect(screen.getByText('Ask how costs changed.')).toBeInTheDocument()
  })

  it('streams a web lookup after an abstention, apart from document citations', async () => {
    const { applyEvent, startAnswer } = await import('./answerReducer')
    let a = startAnswer('What does BLEU stand for?')
    a = applyEvent(a, { event: 'web_searching', data: { query: 'BLEU machine translation full form' } })
    const { rerender, container } = render(<AssistantMessage id="w1" {...a} />)
    expect(screen.getByText('I couldn’t find an answer to this in your document, so I’m checking the web as well.')).toBeInTheDocument()
    expect(screen.getByText(/Searching the web for “BLEU machine translation full form”/)).toBeInTheDocument()

    const web = {
      status: 'answered' as const,
      query: 'BLEU machine translation full form',
      segments: [{ text: 'BLEU stands for Bilingual Evaluation Understudy.', sources: [0] }],
      sources: [
        { title: 'Example reference', uri: 'https://example.org/bleu', domain: 'example.org' },
        { title: 'Unused', uri: 'https://unused.example', domain: 'unused.example' },
      ],
      search_queries: [],
      engine: 'Tavily',
      note: null,
    }
    a = applyEvent(applyEvent(a, { event: 'web', data: web }), { event: 'done', data: { status: 'insufficient_evidence' } })
    rerender(<AssistantMessage id="w1" {...a} />)
    expect(screen.getByText('BLEU stands for Bilingual Evaluation Understudy.')).toBeInTheDocument()
    expect(screen.getByText('I couldn’t find an answer to this in your document, so I checked the web as well.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Example reference/ })).toHaveAttribute('href', 'https://example.org/bleu')
    expect(screen.queryByText(/Unused/)).toBeNull() // only sources that back a sentence are listed
    expect(screen.queryByRole('button', { name: /^Citation/ })).toBeNull()
    expect(screen.getByText('via Tavily')).toBeInTheDocument()
    expect(container.querySelector('iframe')).toBeNull() // no third-party HTML any more
  })

  it('explains an unavailable web lookup', () => {
    const web = { status: 'unavailable' as const, query: 'q', segments: [], sources: [], search_queries: [], note: 'Web search quota is used up for this API key.' }
    render(<AssistantMessage id="w2" status="insufficient_evidence" segments={[]} web={web} />)
    expect(screen.getByText('Web search quota is used up for this API key.')).toBeInTheDocument()
  })

  it('shows retracted text as removed, never with a citation', () => {
    render(
      <AssistantMessage id="m2" status="partial" segments={[{ text: 'Made-up claim.', citations: [], retracted: 'no_valid_evidence' }]} />,
    )
    expect(screen.getByText(/Made-up claim/)).toHaveClass('line-through')
    expect(screen.queryByRole('button', { name: /Citation/ })).toBeNull()
  })

  it('abstains with closest passages', () => {
    render(
      <AssistantMessage
        id="m3"
        status="insufficient_evidence"
        segments={[]}
        closest={[{ block_id: 'pdf:1:0:aa', page: 1, quote: 'Nearby text', location: cite.location }]}
      />,
    )
    expect(screen.getByText('I couldn’t find an answer to this in your document. Asking it in other words may help.')).toBeInTheDocument()
    expect(screen.getByText(/Nearby text/)).toBeInTheDocument()
  })

  it('flags low-confidence evidence', () => {
    render(<AssistantMessage id="m4" status="answered" segments={[{ text: 'x', citations: [{ ...cite, flags: ['low_confidence'] }] }]} />)
    expect(screen.getByRole('button', { name: 'Citation 1, page 4' })).toHaveClass('text-warn')
  })
})

describe('stopped answers', () => {
  it('keeps only verified sentences and says the response was stopped', async () => {
    const { applyEvent, startAnswer, stopAnswer } = await import('./answerReducer')
    let a = startAnswer('q')
    for (const e of [
      { event: 'meta', data: { message_id: 'm9', user_message_id: 'u9' } },
      { event: 'text_delta', data: { segment: 0, text: 'Revenue was $4.2M.' } },
      { event: 'citation', data: { segment: 0, index: 0, citation: cite } },
      { event: 'text_delta', data: { segment: 1, text: 'Half a sentence' } },
    ])
      a = applyEvent(a, e)
    a = stopAnswer(a)
    expect(a.status).toBe('stopped')
    expect(a.userMessageId).toBe('u9')
    expect(a.segments.map((s) => s.text)).toEqual(['Revenue was $4.2M.'])
    render(<AssistantMessage id="m9" segments={a.segments} status={a.status} />)
    expect(screen.getByText('Response stopped. Only verified sentences are kept.')).toBeInTheDocument()
    expect(screen.queryByText(/Half a sentence/)).toBeNull()
    expect(screen.getByRole('article')).toHaveAttribute('aria-busy', 'false')
  })

  it('shows a plain note when stopped before any answer', () => {
    render(<AssistantMessage id="m8" segments={[]} status="stopped" />)
    expect(screen.getByText('Response stopped.')).toBeInTheDocument()
    expect(screen.queryByText(/Reading the whole document/)).toBeNull()
  })
})

describe('AnyDoc mark beside the answer', () => {
  const mark = (c: HTMLElement) => c.querySelector('svg.ad-mark')!

  it('thinks before text, streams with text, rests when done', () => {
    const { container, rerender } = render(<AssistantMessage id="m" status="streaming" segments={[]} live />)
    expect(mark(container).getAttribute('data-state')).toBe('thinking')
    expect(mark(container).hasAttribute('data-enter')).toBe(true)
    rerender(<AssistantMessage id="m" status="streaming" segments={[{ text: 'Q3 revenue', citations: [] }]} live />)
    expect(mark(container).getAttribute('data-state')).toBe('streaming')
    rerender(<AssistantMessage id="m" status="answered" segments={[{ text: 'Q3 revenue.', citations: [] }]} live />)
    expect(mark(container).getAttribute('data-state')).toBe('idle')
  })

  it('does not replay the arrival for saved answers', () => {
    const { container } = render(<AssistantMessage id="m" status="answered" segments={[{ text: 'Done.', citations: [] }]} />)
    expect(mark(container).hasAttribute('data-enter')).toBe(false)
  })
})

describe('failed answers', () => {
  it('show the mark and a readable error, with no empty answer', () => {
    const { container } = render(<AssistantMessage id="m" status="error" segments={[]} error="The AI model is busy right now." />)
    expect(container.querySelector('svg.ad-mark')).not.toBeNull()
    expect(screen.getByRole('alert')).toHaveTextContent('The AI model is busy right now.')
    expect(container.querySelector('article > p:not([role=alert])')).toBeNull()
  })
})
