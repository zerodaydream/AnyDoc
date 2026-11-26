import { Check, ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { Menu, MenuItem } from '../../components/ui/Menu'
import { useUi } from '../../stores/ui'
import type { ModelInfo } from '../../lib/api'
import { formatTokens, LEVEL_NOTE, shortName, useModelChoice } from './modelChoice'

const PROVIDER_NAME: Record<string, string> = { gemini: 'Gemini', groq: 'Groq' }

export function ModelControls() {
  const { data, current, levels, level } = useModelChoice()
  const { setModel, setThinking } = useUi()
  if (!data || !current) return null

  return (
    <div className="flex items-center gap-0.5">
      <Menu label="Thinking" disabled={!levels.length} title={current.thinking ? 'Thinking' : `${shortName(current)} doesn’t think`} trigger={
        <>
          <span aria-hidden className={level === 'off' ? 'text-muted' : 'text-accent'}>✻</span>
          <span className="capitalize">{level === 'off' ? 'No thinking' : level}</span>
          <ChevronDown size={13} />
        </>
      }>
        {(close) => (
          <>
            <p className="px-2.5 pb-1 pt-1.5 text-[12px] text-muted">Thinking</p>
            {[...levels, 'off'].map((l) => (
              <MenuItem key={l} selected={l === level} onSelect={() => { setThinking(l); close() }}>
                <span className="flex-1">
                  <span className="block capitalize text-fg">{l === 'off' ? 'Off' : l}</span>
                  <span className="block text-[12px] text-muted">{l === 'off' ? 'Answer directly' : (LEVEL_NOTE[l] ?? '')}</span>
                </span>
                {l === level && <Check size={14} className="text-accent" />}
              </MenuItem>
            ))}
          </>
        )}
      </Menu>
      <Menu label="Model" trigger={<><span>{shortName(current)}</span><ChevronDown size={13} /></>}>
        {(close) => <ModelMenu models={data.models} current={current} onPick={(id) => { setModel(id); close() }} />}
      </Menu>
    </div>
  )
}

/** Model list with one tab per provider (shown when more than one has a key). Opens on the current model's tab. */
function ModelMenu({ models, current, onPick }: { models: ModelInfo[]; current: ModelInfo; onPick: (id: string) => void }) {
  const providers = [...new Set(models.map((m) => m.provider))]
  const [tab, setTab] = useState(current.provider)
  return (
    <>
      <div className="flex items-center justify-between gap-3 py-1 pl-2.5 pr-1">
        <p className="text-[12px] text-muted">Model</p>
        {providers.length > 1 && (
          <div role="group" aria-label="Provider" className="flex rounded-lg bg-surface p-0.5">
            {providers.map((p) => (
              <button
                key={p}
                type="button"
                aria-pressed={p === tab}
                onClick={() => setTab(p)}
                className={`rounded-md px-2.5 py-0.5 text-[12px] ${p === tab ? 'bg-line/70 text-fg' : 'text-muted hover:text-fg'}`}
              >
                {PROVIDER_NAME[p] ?? p}
              </button>
            ))}
          </div>
        )}
      </div>
      {models
        .filter((m) => m.provider === tab)
        .map((m) => (
          <MenuItem key={m.id} selected={m.id === current.id} disabled={!m.available} onSelect={() => onPick(m.id)}>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-fg">{m.name}</span>
              <span className="block text-[12px] text-muted">
                {m.available ? `${formatTokens(m.input_token_limit)} context${m.thinking ? ', thinks' : ''}` : 'Unavailable right now'}
              </span>
            </span>
            {m.id === current.id && <Check size={14} className="text-accent" />}
          </MenuItem>
        ))}
    </>
  )
}
