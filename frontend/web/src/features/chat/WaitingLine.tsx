import { useEffect, useState } from 'react'
import { WAIT_LINES } from './waitLines'

/**
 * Shown while the answer is being prepared and the model hasn't sent any thoughts or text yet. Lines describe the
 * stages every answer goes through, in order, then rest on the last one: no counts or internals, nothing that
 * pretends to report a specific step.
 */
const STEP_MS = 2400

/**
 * Shown while the answer is being prepared and the model hasn't sent any thoughts or text yet. Lines describe the
 * stages every answer goes through, in order, then rest on the last one: no counts or internals, nothing that
 * pretends to report a specific step.
 */

export function WaitingLine() {
  const [i, setI] = useState(0)
  useEffect(() => {
    if (i >= WAIT_LINES.length - 1) return
    const t = setTimeout(() => setI(i + 1), STEP_MS)
    return () => clearTimeout(t)
  }, [i])
  return (
    <p className="font-sans text-[14px] text-muted" aria-live="polite">
      <span key={i} className="ad-wait-line">
        <span className="ad-shimmer">{WAIT_LINES[i]}</span>
      </span>
    </p>
  )
}
