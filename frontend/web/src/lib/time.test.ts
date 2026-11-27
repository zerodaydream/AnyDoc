import { describe, expect, it } from 'vitest'
import { ago } from './time'

describe('ago', () => {
  const now = new Date(2026, 10, 28, 15, 0, 0).getTime()
  const at = (...a: [number, number, number, number?, number?]) => new Date(...(a as [number, number, number, number, number])).toISOString()

  it('reads like a list timestamp', () => {
    expect(ago(new Date(now - 20_000).toISOString(), now)).toBe('just now')
    expect(ago(new Date(now - 5 * 60_000).toISOString(), now)).toBe('5 min ago')
    expect(ago(at(2026, 10, 28, 9, 30), now)).toBe('5 h ago')
    expect(ago(at(2026, 10, 27, 23, 0), now)).toBe('Yesterday')
    expect(ago(at(2026, 10, 12, 10, 0), now)).toMatch(/12/)
    expect(ago(at(2025, 10, 12, 10, 0), now)).toMatch(/2025/)
  })
})
