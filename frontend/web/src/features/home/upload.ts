import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useState } from 'react'
import { api } from '../../lib/api'
import { useUi } from '../../stores/ui'

export const MAX_MB = 100

export const manyFiles = (n: number) =>
  `That’s ${n} files. AnyDoc reads one file per conversation, so drop them one at a time.`

export type Upload = {
  take: (files?: FileList | File[] | null) => void // one file; more than one is refused with a message
  busy: boolean
  error: string | null
  extensions: string[]
  kinds: string // "PDF, DOCX or CSV"
}

/** One upload flow for the whole app: the Home picker and a file dropped anywhere both start a new conversation. */
export function useUploadFlow(): Upload {
  const qc = useQueryClient()
  const openSession = useUi((s) => s.openSession)
  const formats = useQuery({ queryKey: ['formats'], queryFn: api.formats, staleTime: Infinity })
  const extensions = formats.data?.flatMap((f) => f.extensions) ?? []
  const labels = formats.data?.map((f) => f.label) ?? ['PDF']
  const kinds = labels.length > 1 ? `${labels.slice(0, -1).join(', ')} or ${labels.at(-1)}` : labels[0]
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

  const take = (files?: FileList | File[] | null) => {
    setLocalError(null)
    upload.reset()
    start.reset()
    const list = [...(files ?? [])]
    if (list.length > 1) return setLocalError(manyFiles(list.length))
    const file = list[0]
    if (!file) return
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
    // Before the list loads, let the server decide: it validates every upload anyway.
    if (formats.data && (!file.name.includes('.') || !extensions.includes(ext)))
      return setLocalError(`${file.name} isn’t a file AnyDoc reads yet. Upload ${kinds}.`)
    if (file.size > MAX_MB * 2 ** 20) return setLocalError(`${file.name} is larger than ${MAX_MB} MB.`)
    upload.mutate(file)
  }

  return {
    take,
    busy: upload.isPending || start.isPending,
    error: localError ?? upload.error?.message ?? start.error?.message ?? null,
    extensions,
    kinds,
  }
}

export const UploadContext = createContext<Upload | null>(null)

export function useUpload(): Upload {
  const u = useContext(UploadContext)
  if (!u) throw new Error('useUpload needs <FileDrop> above it')
  return u
}
