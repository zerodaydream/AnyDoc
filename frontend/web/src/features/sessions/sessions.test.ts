import { describe, expect, it } from 'vitest'
import { starterQuestions } from '../chat/starters'
import { bucket } from './bucket'

describe('conversation recency groups', () => {
  const now = new Date('2026-11-25T15:00:00').getTime()
  it.each([
    ['2026-11-25T08:00:00', 'Today'],
    ['2026-11-24T23:59:00', 'Yesterday'],
    ['2026-11-20T10:00:00', 'Previous 7 days'],
    ['2026-11-01T10:00:00', 'Previous 30 days'],
    ['2026-06-01T10:00:00', 'Older'],
  ])('%s -> %s', (iso, want) => expect(bucket(iso, now)).toBe(want))
})

describe('starter questions', () => {
  it('come from real headings, skipping title, boilerplate, numbering and repeats', () => {
    const h = (text: string, page: number) => ({ text, ref: `page ${page}` })
    const qs = starterQuestions([
      h('Attention Is All You Need', 1),
      h('Abstract', 1),
      h('1 Introduction', 2),
      h('3.2.1 Scaled Dot-Product Attention', 4),
      h('References', 10),
      h('3.2.1 Scaled Dot-Product Attention', 4),
    ])
    expect(qs).toEqual([
      { label: 'Introduction', ref: 'page 2', question: 'What does the section “Introduction” say?' },
      { label: 'Scaled Dot-Product Attention', ref: 'page 4', question: 'What does the section “Scaled Dot-Product Attention” say?' },
    ])
  })
})
