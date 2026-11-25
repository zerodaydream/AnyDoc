/** Recency group for the conversation list, relative to local midnight. */
const DAY = 86_400_000

export function bucket(iso: string, now = Date.now()): string {
  const start = new Date(now).setHours(0, 0, 0, 0)
  const t = new Date(iso).getTime()
  if (t >= start) return 'Today'
  if (t >= start - DAY) return 'Yesterday'
  if (t >= start - 7 * DAY) return 'Previous 7 days'
  if (t >= start - 30 * DAY) return 'Previous 30 days'
  return 'Older'
}
