import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Tooltip } from './Tooltip'

describe('Tooltip', () => {
  afterEach(() => vi.useRealTimers())

  it('opens after the hover delay, only when allowed, and closes on leave', () => {
    vi.useFakeTimers()
    render(
      <Tooltip content="Full conversation title" delay={300}>
        <button>row</button>
      </Tooltip>,
    )
    fireEvent.mouseEnter(screen.getByText('row').parentElement!)
    act(() => vi.advanceTimersByTime(200))
    expect(screen.queryByRole('tooltip')).toBeNull() // not before the delay
    act(() => vi.advanceTimersByTime(150))
    expect(screen.getByRole('tooltip')).toHaveTextContent('Full conversation title')
    fireEvent.mouseLeave(screen.getByText('row').parentElement!)
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('stays closed when the text is not truncated', () => {
    vi.useFakeTimers()
    render(
      <Tooltip content="Short" when={() => false}>
        <button>row</button>
      </Tooltip>,
    )
    fireEvent.mouseEnter(screen.getByText('row').parentElement!)
    act(() => vi.advanceTimersByTime(1000))
    expect(screen.queryByRole('tooltip')).toBeNull()
  })
})
