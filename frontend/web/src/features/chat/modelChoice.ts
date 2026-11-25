import { useQuery } from '@tanstack/react-query'
import { api, type ModelInfo, type ModelsOut } from '../../lib/api'
import { useUi } from '../../stores/ui'

export const LEVEL_NOTE: Record<string, string> = {
  minimal: 'Fastest, almost no reasoning',
  low: 'Quick answers',
  medium: 'Balanced',
  high: 'Careful, slower',
  xhigh: 'Most thorough, slowest',
}

export const formatTokens = (n: number | null) =>
  n == null ? 'limit unknown' : n >= 1_000_000 ? `${+(n / 1_048_576).toFixed(1)}M tokens` : `${Math.round(n / 1024)}K tokens`

export const shortName = (m: ModelInfo) => m.name.replace(/^Gemini\s+/i, '')

/** Resolve stored preferences against what the server currently allows. */
const ORDER = ['minimal', 'low', 'medium', 'high', 'xhigh']

/** Nearest supported level (minimal -> low, xhigh -> high); ties go to the cheaper one. Mirrors backend clamp_level. */
export function clampLevel(level: string, supported: string[]): string {
  if (supported.includes(level) || !supported.length) return level
  const i = ORDER.includes(level) ? ORDER.indexOf(level) : 2
  return [...supported].sort((a, b) => Math.abs(ORDER.indexOf(a) - i) - Math.abs(ORDER.indexOf(b) - i) || ORDER.indexOf(a) - ORDER.indexOf(b))[0]
}

export function useModelChoice() {
  const q = useQuery({ queryKey: ['models'], queryFn: api.models, staleTime: 5 * 60_000 })
  const { model, thinking } = useUi()
  const data: ModelsOut | undefined = q.data
  const current = data?.models.find((m) => m.id === model) ?? data?.models.find((m) => m.id === data.default_model)
  const levels = current?.thinking_levels ?? []
  // The remembered preference is clamped to what this model accepts (same rule as the server).
  const level = !levels.length ? 'off' : thinking === 'off' ? 'off' : clampLevel(thinking ?? current?.default_thinking ?? 'medium', levels)
  return { data, current, levels, level, maxChars: data?.max_question_chars ?? 4000 }
}

export const formatSeconds = (ms: number) => (ms < 10_000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms / 1000)}s`)
