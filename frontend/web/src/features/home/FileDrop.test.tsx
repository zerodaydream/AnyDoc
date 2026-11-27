import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type DocumentOut } from '../../lib/api'
import { useUi } from '../../stores/ui'
import { FileDrop } from './FileDrop'
import { Home } from './Home'

const doc = (over: Partial<DocumentOut> = {}): DocumentOut => ({
  id: 'd1',
  title: 'sample copy',
  filename: 'sample copy.csv',
  format: 'csv',
  size_bytes: 10,
  page_count: null,
  extent: '30 rows, 5 columns',
  version: 1,
  status: 'ready',
  progress: 1,
  stage_detail: null,
  error: null,
  file_url: '/f',
  created_at: new Date(Date.now() - 3 * 60_000).toISOString(),
  ingested_at: new Date(Date.now() - 2 * 60_000).toISOString(),
  ...over,
})

function fire(type: string, files: File[] = [], dragging = files.length) {
  const e = new Event(type, { bubbles: true, cancelable: true })
  const items = Array.from({ length: dragging }, () => ({ kind: 'file' }))
  Object.defineProperty(e, 'dataTransfer', { value: { types: ['Files'], files, items, dropEffect: 'none' } })
  act(() => {
    window.dispatchEvent(e)
  })
  return e
}

function mount(child = <p>conversation list</p>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <FileDrop>{child}</FileDrop>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.spyOn(api, 'formats').mockResolvedValue([{ format: 'csv', label: 'CSV', extensions: ['.csv'] }] as never)
  vi.spyOn(api, 'listDocuments').mockResolvedValue([doc()])
  useUi.setState({ sessionId: 'open-session' })
})
afterEach(() => vi.restoreAllMocks())

describe('FileDrop', () => {
  it('shows a + target while a file is dragged anywhere, and hides it when the drag leaves', () => {
    mount()
    expect(screen.queryByText('Drop to start a new conversation')).toBeNull()
    fire('dragenter')
    fire('dragenter') // entering a child element
    expect(screen.getByText('Drop to start a new conversation')).toBeInTheDocument()
    fire('dragleave')
    expect(screen.getByText('Drop to start a new conversation')).toBeInTheDocument()
    fire('dragleave')
    expect(screen.queryByText('Drop to start a new conversation')).toBeNull()
  })

  it('a drop goes to the fresh area and starts a new conversation about the file', async () => {
    const upload = vi.spyOn(api, 'upload').mockResolvedValue(doc({ id: 'new' }))
    const create = vi.spyOn(api, 'createSession').mockResolvedValue({ id: 's-new' } as never)
    mount()
    await waitFor(() => expect(api.formats).toHaveBeenCalled())
    const file = new File(['a,b\n1,2\n'], 'data.csv', { type: 'text/csv' })
    fire('dragenter')
    const e = fire('drop', [file])
    expect(e.defaultPrevented).toBe(true) // the browser doesn't open the file
    expect(screen.queryByText('Drop to start a new conversation')).toBeNull()
    await waitFor(() => expect(upload.mock.calls[0]?.[0]).toBe(file)) // react-query passes a context too
    await waitFor(() => expect(create.mock.calls[0][0]).toBe('new'))
    await waitFor(() => expect(useUi.getState().sessionId).toBe('s-new'))
  })

  it('warns while more than one file is dragged, and refuses the drop with a clear message', async () => {
    const upload = vi.spyOn(api, 'upload')
    mount(<Home />)
    fire('dragenter', [], 3)
    expect(screen.getByText('One file at a time')).toBeInTheDocument()
    expect(screen.queryByText('Drop to start a new conversation')).toBeNull()
    const files = ['a.csv', 'b.csv', 'c.csv'].map((n) => new File(['a,b\n1,2\n'], n))
    fire('drop', files)
    expect(screen.queryByText('One file at a time')).toBeNull()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'That’s 3 files. AnyDoc reads one file per conversation, so drop them one at a time.',
    )
    expect(useUi.getState().sessionId).toBeNull() // taken to the fresh area, where the message shows
    expect(upload).not.toHaveBeenCalled()
  })

  it('ignores drags that carry no files (text, links)', () => {
    mount()
    const e = new Event('dragenter', { bubbles: true, cancelable: true })
    Object.defineProperty(e, 'dataTransfer', { value: { types: ['text/plain'], files: [] } })
    act(() => {
      window.dispatchEvent(e)
    })
    expect(screen.queryByText('Drop to start a new conversation')).toBeNull()
  })
})

describe('Home', () => {
  it('shows when each document was added, with both times on hover', async () => {
    useUi.setState({ sessionId: null })
    mount(<Home />)
    const time = await screen.findByText('3 min ago')
    expect(time.tagName).toBe('TIME')
    expect(time.getAttribute('aria-label')).toMatch(/^Added .+ · Ready .+/)
    expect(screen.getByText(/30 rows, 5 columns/)).toBeInTheDocument()
  })

  it('rejects an unsupported dropped file in the fresh area', async () => {
    useUi.setState({ sessionId: null })
    const upload = vi.spyOn(api, 'upload')
    mount(<Home />)
    await screen.findByText('3 min ago')
    fire('drop', [new File(['x'], 'photo.png')])
    expect(await screen.findByRole('alert')).toHaveTextContent('photo.png isn’t a file AnyDoc reads yet. Upload CSV.')
    expect(upload).not.toHaveBeenCalled()
  })
})
