import { Files, Plus } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useUi } from '../../stores/ui'
import { MAX_MB, UploadContext, useUploadFlow } from './upload'

const hasFiles = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].includes('Files')
// While dragging, browsers expose how many items are coming (not their names); 0 when they don't say.
const fileCount = (e: DragEvent) => [...(e.dataTransfer?.items ?? [])].filter((i) => i.kind === 'file').length

/**
 * Drop a file in the app (Home, the conversation list, an open conversation): a full-window target with a
 * "+" appears, and the drop opens the Home screen and starts a new conversation about that file.
 */
export function FileDrop({ children }: { children: ReactNode }) {
  const upload = useUploadFlow()
  const openSession = useUi((s) => s.openSession)
  const [over, setOver] = useState<false | 'one' | 'many'>(false)
  const depth = useRef(0) // dragenter/dragleave fire for every child element; count them
  const takeRef = useRef(upload.take)
  useEffect(() => {
    takeRef.current = upload.take
  })

  useEffect(() => {
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      depth.current++
      setOver(fileCount(e) > 1 ? 'many' : 'one')
    }
    const overWin = (e: DragEvent) => {
      if (!hasFiles(e)) return
      e.preventDefault() // without this the browser opens the file instead of dropping it here
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
    }
    const leave = (e: DragEvent) => {
      if (!hasFiles(e)) return
      depth.current = Math.max(0, depth.current - 1)
      if (depth.current === 0) setOver(false)
    }
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      depth.current = 0
      setOver(false)
      const files = e.dataTransfer?.files
      if (!files?.length) return
      openSession(null) // the fresh (Home) area shows the upload and any error (e.g. too many files)
      takeRef.current(files)
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragover', overWin)
    window.addEventListener('dragleave', leave)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragover', overWin)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('drop', drop)
    }
  }, [openSession])

  return (
    <UploadContext.Provider value={upload}>
      {children}
      {over && (
        <div
          className="pointer-events-none fixed inset-0 z-50 grid place-items-center bg-bg/75 p-6 backdrop-blur-[2px]"
          role="status"
          aria-live="polite"
        >
          {over === 'many' ? (
            <div className="flex size-full max-h-[420px] max-w-[560px] flex-col items-center justify-center gap-4 rounded-3xl border-2 border-dashed border-warn bg-warn/8 text-center">
              <span className="grid size-14 place-items-center rounded-2xl bg-warn/15 text-warn">
                <Files size={26} aria-hidden />
              </span>
              <div>
                <p className="font-serif text-[22px] leading-8 text-fg">One file at a time</p>
                <p className="mt-1 text-[13px] text-muted">Each conversation is about a single document.</p>
              </div>
            </div>
          ) : (
            <div className="flex size-full max-h-[420px] max-w-[560px] flex-col items-center justify-center gap-4 rounded-3xl border-2 border-dashed border-accent bg-accent/8 text-center">
              <span className="grid size-14 place-items-center rounded-2xl bg-accent text-on-accent">
                <Plus size={28} strokeWidth={2.25} aria-hidden />
              </span>
              <div>
                <p className="font-serif text-[22px] leading-8 text-fg">Drop to start a new conversation</p>
                <p className="mt-1 text-[13px] text-muted">
                  {upload.kinds}, up to {MAX_MB} MB
                </p>
              </div>
            </div>
          )}
        </div>
      )}
    </UploadContext.Provider>
  )
}
