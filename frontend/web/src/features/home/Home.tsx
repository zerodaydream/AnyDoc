import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { api } from '../../lib/api'
import { useUi } from '../../stores/ui'

const MAX_MB = 100

export function Home() {
  const qc = useQueryClient()
  const openSession = useUi((s) => s.openSession)
  const docs = useQuery({ queryKey: ['documents'], queryFn: api.listDocuments })
  const formats = useQuery({ queryKey: ['formats'], queryFn: api.formats, staleTime: Infinity })
  const extensions = formats.data?.flatMap((f) => f.extensions) ?? []
  const labels = formats.data?.map((f) => f.label) ?? ['PDF']
  const kinds = labels.length > 1 ? `${labels.slice(0, -1).join(', ')} or ${labels.at(-1)}` : labels[0]
  const picker = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  const start = useMutation({
    mutationFn: api.createSession,
    onSuccess: async (s) => {
      await qc.invalidateQueries({ queryKey: ['sessions'] })
      openSession(s.id)
    },
  })
  const upload = useMutation({
    mutationFn: api.upload,
    onSuccess: async (doc) => {
      void qc.invalidateQueries({ queryKey: ['documents'] })
      start.mutate(doc.id)
    },
  })

  const take = (file?: File) => {
    setLocalError(null)
    if (!file) return
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
    // Before the list loads, let the server decide: it validates every upload anyway.
    if (formats.data && (!file.name.includes('.') || !extensions.includes(ext))) return setLocalError(`${file.name} isn’t a file AnyDoc reads yet. Upload ${kinds}.`)
    if (file.size > MAX_MB * 2 ** 20) return setLocalError(`${file.name} is larger than ${MAX_MB} MB.`)
    upload.mutate(file)
  }
  const error = localError ?? upload.error?.message ?? start.error?.message
  const busy = upload.isPending || start.isPending
  const recent = (docs.data ?? []).filter((d) => d.status === 'ready').slice(0, 6)

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex max-w-[640px] flex-col px-6 pb-16 pt-[14vh]">
        <h1 className="font-serif text-[34px] leading-[42px] tracking-[-0.015em] text-fg">
          Ask your document. See where every answer comes from.
        </h1>
        <p className="mt-3 max-w-[52ch] text-[16px] leading-[26px] text-muted">
          Each answer is checked against the file and pinned to the exact line it quotes. If the document doesn’t say,
          AnyDoc tells you.
        </p>

        <div
          onDragOver={(e) => {
            e.preventDefault()
            setOver(true)
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setOver(false)
            take(e.dataTransfer.files[0])
          }}
          className={`mt-9 flex items-center gap-4 rounded-2xl border border-dashed px-5 py-5 transition-colors ${
            over ? 'border-accent bg-accent/8' : 'border-line bg-bg'
          }`}
        >
          <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-surface text-accent">
            <Upload size={19} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-fg">{busy ? 'Uploading…' : 'Drop a file here'}</p>
            <p className="text-[13px] text-muted">
              {kinds}, up to {MAX_MB} MB
            </p>
          </div>
          <button
            type="button"
            onClick={() => picker.current?.click()}
            disabled={busy}
            className="h-9 shrink-0 rounded-lg bg-accent px-3.5 font-medium text-on-accent hover:bg-accent-strong disabled:opacity-60"
          >
            Choose file
          </button>
          <input ref={picker} type="file" accept={extensions.join(',')} hidden onChange={(e) => take(e.target.files?.[0])} />
        </div>
        {error && (
          <p role="alert" className="mt-3 text-danger">
            {error}
          </p>
        )}

        {recent.length > 0 && (
          <section className="mt-12">
            <h2 className="text-[13px] font-medium text-muted">Start a new conversation about</h2>
            <ul className="mt-2 divide-y divide-line border-y border-line">
              {recent.map((d) => (
                <li key={d.id}>
                  <button
                    onClick={() => start.mutate(d.id)}
                    disabled={busy}
                    className="group flex w-full items-center gap-3 px-1 py-3 text-left hover:bg-surface/50"
                  >
                    <FileText size={17} className="shrink-0 text-muted group-hover:text-accent" />
                    <span className="min-w-0 flex-1 truncate text-fg">{d.title}</span>
                    <span className="shrink-0 text-[13px] tabular-nums text-muted">{d.extent}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  )
}
