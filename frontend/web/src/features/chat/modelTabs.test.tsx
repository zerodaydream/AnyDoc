import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ModelInfo } from '../../lib/api'
import { useUi } from '../../stores/ui'
import { ModelControls } from './ModelControls'

const model = (id: string, provider: string, thinking: boolean): ModelInfo => ({
  id,
  provider,
  name: id,
  input_token_limit: 131_072,
  output_token_limit: 8_192,
  thinking,
  available: true,
  thinking_levels: thinking ? ['low', 'high'] : [],
  default_thinking: thinking ? 'low' : null,
})

function renderWith(models: ModelInfo[]) {
  const body = { models, default_model: models[0].id, thinking_levels: ['low', 'high'], default_thinking: 'low', max_question_chars: 4000 }
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })))
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ModelControls />
    </QueryClientProvider>,
  )
}

describe('model picker tabs', () => {
  beforeEach(() => useUi.setState({ model: null, thinking: null }))

  it('switches between Gemini and Groq models and picks from the open tab', async () => {
    renderWith([model('gemini-a', 'gemini', true), model('llama-3.3-70b-versatile', 'groq', false)])
    await userEvent.click(await screen.findByRole('button', { name: 'Model' }))
    expect(screen.getByRole('button', { name: 'Gemini', pressed: true })).toBeInTheDocument()
    expect(within(screen.getByRole('menu')).queryByText('llama-3.3-70b-versatile')).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Groq' }))
    expect(within(screen.getByRole('menu')).queryByText('gemini-a')).toBeNull()
    await userEvent.click(screen.getByRole('menuitemradio', { name: /llama-3.3-70b-versatile/ }))
    expect(useUi.getState().model).toBe('llama-3.3-70b-versatile')
    expect(await screen.findByText('No thinking')).toBeInTheDocument() // Groq models answer directly

    await userEvent.click(screen.getByRole('button', { name: 'Model' }))
    expect(screen.getByRole('button', { name: 'Groq', pressed: true })).toBeInTheDocument() // opens on the current tab
  })

  it('shows no tabs with a single provider', async () => {
    renderWith([model('gemini-a', 'gemini', true), model('gemini-b', 'gemini', true)])
    await userEvent.click(await screen.findByRole('button', { name: 'Model' }))
    expect(screen.queryByRole('group', { name: 'Provider' })).toBeNull()
    expect(screen.getByText('gemini-b')).toBeInTheDocument()
  })
})

describe('a model that thinks on request', () => {
  beforeEach(() => useUi.setState({ model: null, thinking: null }))

  it('starts with thinking off when that is its default, and still offers levels', async () => {
    renderWith([{ ...model('qwen/qwen3.8-27b', 'groq', true), default_thinking: 'off' }])
    expect(await screen.findByText('No thinking')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Thinking' }))
    expect(screen.getByRole('menuitemradio', { name: /^low/i })).toBeInTheDocument()
  })
})
