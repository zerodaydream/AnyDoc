import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Circle, LoaderCircle } from 'lucide-react'
import { api, type DocumentOut } from '../../lib/api'
import { useUi } from '../../stores/ui'

const STEPS: { label: string; states: string[] }[] = [
  { label: 'Uploading', states: ['pending', 'uploading'] },
  { label: 'Checking file', states: ['uploaded', 'validating', 'queued'] },
  { label: 'Reading pages', states: ['processing'] },
  { label: 'Indexing', states: ['indexing'] },
  { label: 'Ready', states: ['ready'] },
]

export function ProcessingState({ doc }: { doc: DocumentOut }) {
  const qc = useQueryClient()
  const setUploading = useUi((s) => s.setUploading)
  const refresh = (d: DocumentOut) => qc.setQueryData(['document', d.id], d)
  const cancel = useMutation({ mutationFn: () => api.cancel(doc.id), onSuccess: refresh })
  const retry = useMutation({ mutationFn: () => api.retry(doc.id), onSuccess: refresh })

  if (doc.status === 'failed' || doc.status === 'cancelled') {
    return (
      <div className="mx-auto max-w-[68ch] px-5 pt-[16vh]">
        <p className="font-serif text-[24px] leading-8 text-fg">
          {doc.status === 'cancelled' ? 'Processing was cancelled.' : 'This document couldn’t be processed.'}
        </p>
        {doc.error && <p className="mt-2 text-[15px] text-muted">{doc.error.message}</p>}
        <div className="mt-5 flex gap-2">
          <button onClick={() => retry.mutate()} className="h-9 rounded-lg bg-accent px-3 text-on-accent hover:bg-accent-strong">
            Try again
          </button>
          <button onClick={() => setUploading(true)} className="h-9 rounded-lg border border-line px-3 text-fg hover:bg-surface">
            Upload another file
          </button>
        </div>
      </div>
    )
  }

  const current = STEPS.findIndex((s) => s.states.includes(doc.status))
  return (
    <div className="mx-auto max-w-[68ch] px-5 pt-[16vh]" aria-live="polite">
      <p className="font-serif text-[24px] leading-8 text-fg">Preparing {doc.title}</p>
      <ol className="mt-5 flex flex-col gap-2.5">
        {STEPS.map((s, i) => (
          <li key={s.label} className={`flex items-center gap-2.5 ${i <= current ? 'text-fg' : 'text-muted'}`}>
            {i < current ? (
              <Check size={16} className="text-accent" aria-hidden />
            ) : i === current ? (
              <LoaderCircle size={16} className="animate-spin text-accent motion-reduce:animate-none" aria-hidden />
            ) : (
              <Circle size={16} aria-hidden />
            )}
            <span>
              {s.label}
              {i === current && s.label === 'Indexing' && ` (${Math.round(doc.progress * 100)}%)`}
              {i === current && s.label === 'Reading pages' && doc.page_count ? ` (${doc.page_count} pages)` : ''}
            </span>
          </li>
        ))}
      </ol>
      <button onClick={() => cancel.mutate()} disabled={cancel.isPending} className="mt-6 text-muted underline-offset-4 hover:text-fg hover:underline">
        Cancel
      </button>
    </div>
  )
}
