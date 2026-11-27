import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type SessionOut } from '../../lib/api'
import { useUi } from '../../stores/ui'
import { Sidebar } from '../sessions/Sidebar'
import { TERMS } from './terms'

const session: SessionOut = {
  id: 's1',
  title: 'Version totals',
  document_id: 'd1',
  document_title: 'sample copy',
  document_status: 'ready',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
} as SessionOut

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <Sidebar />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  useUi.setState({ sessionId: null })
  vi.spyOn(api, 'sessions').mockResolvedValue([session])
})
afterEach(() => vi.restoreAllMocks())

describe('terms and deleting', () => {
  it('opens the terms from the sidebar and lists every point', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(screen.getByRole('button', { name: 'Terms and conditions' }))
    const dialog = screen.getByRole('dialog', { name: 'Terms and conditions' })
    for (const s of TERMS) for (const p of s.points) expect(within(dialog).getByText(p)).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('the first delete explains it, points to the terms, and deletes only on confirm', async () => {
    const user = userEvent.setup()
    const del = vi.spyOn(api, 'deleteSession').mockResolvedValue({ document_deleted: true })
    mount()
    await user.click(await screen.findByRole('button', { name: 'Delete Version totals' }))
    const notice = screen.getByRole('dialog', { name: 'Delete this conversation for good?' })
    expect(notice).toHaveTextContent('can’t be undone')
    await user.click(within(notice).getByRole('button', { name: 'terms on deleting your information' }))
    const terms = screen.getByRole('dialog', { name: 'Terms and conditions' })
    await user.click(within(terms).getByRole('button', { name: 'Got it' }))
    expect(del).not.toHaveBeenCalled()
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('s1'))
    expect(localStorage.getItem('anydoc.deleteNoticeSeen')).toBe('1')
  })

  it('cancelling the notice deletes nothing; later deletes use the quick inline confirm', async () => {
    const user = userEvent.setup()
    const del = vi.spyOn(api, 'deleteSession').mockResolvedValue({ document_deleted: false })
    mount()
    await user.click(await screen.findByRole('button', { name: 'Delete Version totals' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }))
    expect(del).not.toHaveBeenCalled()

    localStorage.setItem('anydoc.deleteNoticeSeen', '1')
    await user.click(screen.getByRole('button', { name: 'Delete Version totals' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Confirm delete Version totals' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('s1'))
  })

  it('shows why a delete was refused', async () => {
    const user = userEvent.setup()
    localStorage.setItem('anydoc.deleteNoticeSeen', '1')
    vi.spyOn(api, 'deleteSession').mockRejectedValue(new Error('Its document is still being processed. Try again when it’s ready.'))
    mount()
    await user.click(await screen.findByRole('button', { name: 'Delete Version totals' }))
    await user.click(screen.getByRole('button', { name: 'Confirm delete Version totals' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('still being processed')
  })
})
