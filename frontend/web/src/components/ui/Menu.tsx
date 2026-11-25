import { useEffect, useRef, useState, type ReactNode } from 'react'

/** Small anchored menu: click to open, Esc or outside click to close, opens upward from the composer. */
export function Menu({
  label,
  trigger,
  children,
  disabled,
  title,
}: {
  label: string
  trigger: ReactNode
  children: (close: () => void) => ReactNode
  disabled?: boolean
  title?: string
}) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: KeyboardEvent | MouseEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !root.current?.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('keydown', close)
    window.addEventListener('mousedown', close)
    return () => {
      window.removeEventListener('keydown', close)
      window.removeEventListener('mousedown', close)
    }
  }, [open])
  return (
    <div ref={root} className="relative">
      <button
        type="button"
        disabled={disabled}
        title={title}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={`flex h-8 items-center gap-1.5 rounded-lg px-2 text-[13px] text-muted hover:bg-line/60 hover:text-fg disabled:opacity-50 disabled:hover:bg-transparent ${open ? 'bg-line/60 text-fg' : ''}`}
      >
        {trigger}
      </button>
      {open && (
        <div role="menu" aria-label={label} className="absolute bottom-10 right-0 z-30 min-w-56 rounded-xl border border-line bg-bg p-1 shadow-[0_8px_30px_rgb(0_0_0/0.35)]">
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  )
}

export function MenuItem({
  selected,
  onSelect,
  children,
  disabled,
}: {
  selected: boolean
  onSelect: () => void
  children: ReactNode
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={selected}
      disabled={disabled}
      onClick={onSelect}
      className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-[13px] disabled:opacity-40 ${
        selected ? 'bg-surface text-fg' : 'text-fg/90 hover:bg-surface/70'
      }`}
    >
      {children}
    </button>
  )
}
