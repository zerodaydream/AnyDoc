import { Check, ChevronDown } from 'lucide-react'
import { Menu, MenuItem } from '../../components/ui/Menu'
import { useUi } from '../../stores/ui'
import { formatTokens, LEVEL_NOTE, shortName, useModelChoice } from './modelChoice'

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
        {(close) => (
          <>
            <p className="px-2.5 pb-1 pt-1.5 text-[12px] text-muted">Model</p>
            {data.models.map((m) => (
              <MenuItem key={m.id} selected={m.id === current.id} disabled={!m.available} onSelect={() => { setModel(m.id); close() }}>
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
        )}
      </Menu>
    </div>
  )
}
