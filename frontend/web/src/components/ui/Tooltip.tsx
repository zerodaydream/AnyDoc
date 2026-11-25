import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/**
 * Soft tooltip beside an element (portal, so scroll containers can't clip it).
 * Opens after a short hover/focus delay, only when `when()` is true (e.g. the text is truncated).
 */
export function Tooltip({
  content,
  children,
  when = () => true,
  delay = 380,
}: {
  content: ReactNode
  children: ReactNode
  when?: () => boolean
  delay?: number
}) {
  const anchor = useRef<HTMLSpanElement>(null)
  const timer = useRef<number | undefined>(undefined)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)

  const show = () => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      const el = anchor.current
      if (!el || !when()) return
      const r = el.getBoundingClientRect()
      setPos({ left: r.right + 10, top: r.top + r.height / 2 })
    }, delay)
  }
  const hide = () => {
    window.clearTimeout(timer.current)
    setPos(null)
  }

  useEffect(() => {
    if (!pos) return
    window.addEventListener('scroll', hide, true) // any scroll moves the anchor: close instead of drifting
    return () => window.removeEventListener('scroll', hide, true)
  }, [pos])
  useEffect(() => () => window.clearTimeout(timer.current), [])

  return (
    <span ref={anchor} className="block" onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}>
      {children}
      {pos &&
        createPortal(
          // Outer box centres on the anchor; the inner box animates (both use `translate`, so they can't share).
          <div role="tooltip" style={{ left: pos.left, top: pos.top }} className="pointer-events-none fixed z-50 -translate-y-1/2">
            <div className="ad-tip max-w-[300px] rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[13.5px] leading-5 text-fg shadow-[0_8px_24px_rgb(0_0_0/0.28)]">
              {content}
            </div>
          </div>,
          document.body,
        )}
    </span>
  )
}
