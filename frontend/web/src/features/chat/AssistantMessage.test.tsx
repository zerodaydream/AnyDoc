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
    expect(screen.getByText('The document doesn’t say.')).toBeInTheDocument()
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
