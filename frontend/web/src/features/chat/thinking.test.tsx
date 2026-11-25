import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { applyEvent, startAnswer } from './answerReducer'
import { clampLevel, formatSeconds, formatTokens } from './modelChoice'
import { ThinkingBlock } from './ThinkingBlock'

describe('thinking in the answer stream', () => {
  it('accumulates reasoning, ends the thinking phase at the first answer text, and resets', () => {
    vi.spyOn(Date, 'now').mockReturnValueOnce(1_000).mockReturnValueOnce(4_200)
    let a = applyEvent(startAnswer('q'), { event: 'meta', data: { message_id: 'm', route: 'full_context', blocks: 3, thinking: 'high' } })
    a = applyEvent(a, { event: 'thinking_delta', data: { text: 'Looking for ' } })
    a = applyEvent(a, { event: 'thinking_delta', data: { text: 'the passage.' } })
    expect(a.reasoning).toBe('Looking for the passage.')
    a = applyEvent(a, { event: 'text_delta', data: { segment: 0, text: 'Answer' } })
    expect(a.thinkingMs).toBe(3_200)
    a = applyEvent(a, { event: 'reset', data: {} })
    expect(a).toMatchObject({ reasoning: '', thinkingMs: null, segments: [] })
    vi.restoreAllMocks()
  })
})

describe('ThinkingBlock', () => {
  it('shows a live state, then a collapsed summary that expands to the reasoning', async () => {
    const { rerender } = render(<ThinkingBlock text={'Step one.\nStep two.'} live startedAt={Date.now()} />)
    expect(screen.getByText('Thinking')).toBeInTheDocument()
    expect(screen.getByText('Step two.')).toBeInTheDocument() // latest line previewed while live

    rerender(<ThinkingBlock text={'Step one.\nStep two.'} live={false} ms={4_200} />)
    expect(screen.getByText('for 4.2s')).toBeInTheDocument()
    expect(screen.queryByText(/Step one/)).toBeNull() // collapsed by default
    await userEvent.click(screen.getByRole('button', { expanded: false }))
    expect(screen.getByText(/Step one\.\s+Step two\./)).toBeInTheDocument()
    expect(screen.getByText(/Only the answer below is checked/)).toBeInTheDocument()
  })

  it('renders summary headings and bold without showing markdown', async () => {
    render(<ThinkingBlock text={'**Finding the section**\n\nIt is labeled **5.3**.'} live={false} ms={1_500} />)
    await userEvent.click(screen.getByRole('button', { expanded: false }))
    expect(screen.getByText('Finding the section')).toHaveClass('font-medium')
    expect(screen.getByText('5.3').tagName).toBe('STRONG')
    expect(screen.queryByText(/\*\*/)).toBeNull()
  })
})

describe('formatting', () => {
  it.each([
    [1_048_576, '1M tokens'],
    [131_072, '128K tokens'],
    [null, 'limit unknown'],
  ])('formatTokens(%s) = %s', (n, want) => expect(formatTokens(n)).toBe(want))
  it('formats seconds', () => {
    expect(formatSeconds(4_210)).toBe('4.2s')
    expect(formatSeconds(42_600)).toBe('43s')
  })
})

describe('clampLevel (mirrors the backend)', () => {
  it.each([
    ['minimal', ['low', 'medium', 'high'], 'low'],
    ['xhigh', ['low', 'medium', 'high'], 'high'],
    ['medium', ['low', 'high'], 'low'],
    ['high', ['low', 'medium', 'high', 'xhigh'], 'high'],
  ])('%s within %j -> %s', (lvl, sup, want) => expect(clampLevel(lvl, sup)).toBe(want))
})
