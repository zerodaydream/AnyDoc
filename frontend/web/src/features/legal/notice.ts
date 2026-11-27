/** Whether this browser has seen the first-delete notice (then deletes use the quick inline confirm). */
const KEY = 'anydoc.deleteNoticeSeen'

export function deleteNoticeSeen(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false // private mode: show the notice each time, never skip it
  }
}

export function markDeleteNoticeSeen(): void {
  try {
    localStorage.setItem(KEY, '1')
  } catch {
    /* private mode: shown again next time */
  }
}
