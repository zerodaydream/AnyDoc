import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileUp } from 'lucide-react'
import { useRef, useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { useUi } from '../../stores/ui'

const MAX_MB = 100

export function UploadZone() {
  const qc = useQueryClient()
  const open = useUi((s) => s.openDocument)
  const picker = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const upload = useMutation({
    mutationFn: api.upload,
    onSuccess: async (doc) => {
      await qc.invalidateQueries({ queryKey: ['documents'] })
      open(doc.id)
    },
  })

  const take = (file?: File) => {
    setLocalError(null)
    if (!file) return
    if (!/\.pdf$/i.test(file.name)) return setLocalError(`${file.name} isn't a PDF. Other formats arrive in later versions.`)
    if (file.size > MAX_MB * 2 ** 20) return setLocalError(`${file.name} is larger than ${MAX_MB} MB.`)
    upload.mutate(file)
  }

  const error = localError ?? (upload.error instanceof ApiError || upload.error ? upload.error.message : null)

  return (
    <div className="grid h-full place-items-center bg-bg p-6">
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
        className={`flex w-full max-w-xl flex-col items-start gap-4 rounded-2xl border border-dashed p-10 transition-colors ${
          over ? 'border-accent bg-surface' : 'border-line'
        }`}
      >
        <FileUp size={22} className="text-accent" aria-hidden />
        <div>
          <h1 className="font-serif text-[29px] leading-9 text-fg">Open a document</h1>
          <p className="mt-2 max-w-md text-[15px] leading-6 text-muted">
            Drop a PDF here or choose a file. Answers will link to the exact page and line.
          </p>
        </div>
        <button
          type="button"
          onClick={() => picker.current?.click()}
          disabled={upload.isPending}
          className="h-10 rounded-lg bg-accent px-4 font-medium text-on-accent hover:bg-accent-strong disabled:opacity-60"
        >
          {upload.isPending ? 'Uploading…' : 'Choose file'}
        </button>
        <input ref={picker} type="file" accept="application/pdf,.pdf" hidden onChange={(e) => take(e.target.files?.[0])} />
        {error && (
          <p role="alert" className="text-danger">
            {error}
          </p>
        )}
        <p className="text-[12px] text-muted">PDF up to {MAX_MB} MB and 500 pages.</p>
      </div>
    </div>
  )
}
