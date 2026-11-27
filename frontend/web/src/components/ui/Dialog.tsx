import { X } from 'lucide-react'
import { useEffect, useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/** Small centred modal: Esc, the backdrop or the close button dismiss it; focus moves in and returns on close. */
export function Dialog({
  title,
  onClose,
  children,
  footer,
  layer = 0,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  layer?: number // a dialog opened from another dialog sits above it
}) {
  const id = useId()
  const box = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  })
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null
    const first = box.current?.querySelector<HTMLElement>('[data-autofocus]') ?? box.current
    first?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      closeRef.current()
    }
    const el = box.current
    el?.addEventListener('keydown', onKey)
    return () => {
      el?.removeEventListener('keydown', onKey)
      before?.focus?.()
    }
  }, [])

  return createPortal(
    <div className="fixed inset-0 grid place-items-center p-4" style={{ zIndex: 60 + layer }}>
      <button aria-label="Close" tabIndex={-1} className="absolute inset-0 cursor-default bg-black/55" onClick={onClose} />
      <div
        ref={box}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        tabIndex={-1}
        className="ad-dialog relative flex max-h-[min(640px,88vh)] w-full max-w-[480px] flex-col rounded-2xl border border-line bg-bg shadow-2xl outline-none"
      >
        <header className="flex items-start justify-between gap-4 px-5 pb-2 pt-4">
          <h2 id={id} className="font-serif text-[20px] leading-7 text-fg">
            {title}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="-mr-1.5 grid size-8 shrink-0 place-items-center rounded-md text-muted hover:bg-surface hover:text-fg"
          >
            <X size={16} />
          </button>
        </header>
        <div className="min-h-0 overflow-y-auto px-5 pb-4 text-[14px] leading-[22px] text-fg/90">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer>}
      </div>
    </div>,
    document.body,
  )
}
