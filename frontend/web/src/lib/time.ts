/** Short relative time for lists ("just now", "5 min ago", "Yesterday", "Nov 12"), and a full local stamp. */
const MIN = 60_000
const HOUR = 60 * MIN
const DAY = 24 * HOUR

const dayMonth = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' })
const dayMonthYear = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
const full = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

export function ago(iso: string, now = Date.now()): string {
  const t = new Date(iso).getTime()
  const d = now - t
  if (d < MIN) return 'just now'
  if (d < HOUR) return `${Math.floor(d / MIN)} min ago`
  const midnight = new Date(now).setHours(0, 0, 0, 0)
  if (t >= midnight) return `${Math.floor(d / HOUR)} h ago`
  if (t >= midnight - DAY) return 'Yesterday'
  return (new Date(t).getFullYear() === new Date(now).getFullYear() ? dayMonth : dayMonthYear).format(t)
}

export const stamp = (iso: string) => full.format(new Date(iso))
