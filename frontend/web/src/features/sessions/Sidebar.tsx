import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Moon, PanelLeftClose, Pencil, Plus, Sun, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Tooltip } from '../../components/ui/Tooltip'
import { api, type SessionOut } from '../../lib/api'
import { useUi } from '../../stores/ui'
import { bucket } from './bucket'
import { Wordmark } from '../../components/Logo'

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: api.sessions })
  const { sessionId, openSession, toggleSidebar, theme, toggleTheme } = useUi()

  const groups: [string, SessionOut[]][] = []
  // A conversation is listed once it has a first question (its title), or while it is open.
  for (const s of (sessions.data ?? []).filter((x) => x.title || x.id === sessionId)) {
    const b = bucket(s.updated_at)
    const g = groups.find(([name]) => name === b)
    if (g) g[1].push(s)
    else groups.push([b, [s]])
  }

  return (
    <nav aria-label="Conversations" className="flex h-full w-full flex-col bg-sunken">
      <div className="flex h-14 shrink-0 items-center justify-between pl-4 pr-2">
        <Wordmark />
        <button
          onClick={() => toggleSidebar(false)}
          className="grid size-8 place-items-center rounded-md text-muted hover:bg-surface hover:text-fg"
          aria-label="Hide sidebar"
          title="Hide sidebar (Ctrl+B)"
        >
          <PanelLeftClose size={17} />
        </button>
      </div>
      <div className="px-2 pb-2">
        <button
          onClick={() => {
            openSession(null)
            onNavigate?.()
          }}
          className="flex h-9 w-full items-center gap-2 rounded-lg px-2.5 text-fg hover:bg-surface"
        >
          <span className="grid size-5 place-items-center rounded-full bg-accent text-on-accent">
            <Plus size={13} strokeWidth={2.5} />
          </span>
          New conversation
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {sessions.isSuccess && sessions.data.length === 0 && (
          <p className="px-2.5 pt-2 text-[13px] leading-5 text-muted">Your conversations will appear here.</p>
        )}
        {groups.map(([name, items]) => (
          <section key={name} className="mt-3 first:mt-1">
            <h2 className="px-2.5 pb-1 text-[12px] font-medium text-muted">{name}</h2>
            <ul>
              {items.map((s) => (
                <SessionRow
                  key={s.id}
                  s={s}
                  active={s.id === sessionId}
                  onOpen={() => {
                    openSession(s.id)
                    onNavigate?.()
                  }}
                />
              ))}
            </ul>
          </section>
        ))}
      </div>
      <div className="flex items-center gap-1 border-t border-line px-2 py-2">
        <button
          onClick={toggleTheme}
          className="flex h-8 items-center gap-2 rounded-md px-2 text-[13px] text-muted hover:bg-surface hover:text-fg"
        >
          {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
          {theme === 'dark' ? 'Light theme' : 'Dark theme'}
        </button>
      </div>
    </nav>
  )
}

function SessionRow({ s, active, onOpen }: { s: SessionOut; active: boolean; onOpen: () => void }) {
  const qc = useQueryClient()
  const openSession = useUi((st) => st.openSession)
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const titleRef = useRef<HTMLSpanElement>(null)
  const rename = useMutation({
    mutationFn: (title: string) => api.renameSession(s.id, title),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sessions'] }),
  })
  const remove = useMutation({
    mutationFn: () => api.deleteSession(s.id),
    onSuccess: () => {
      if (active) openSession(null)
      void qc.invalidateQueries({ queryKey: ['sessions'] })
    },
  })

  useEffect(() => {
    if (editing) input.current?.select()
  }, [editing])
  useEffect(() => {
    if (!confirming) return
    const t = setTimeout(() => setConfirming(false), 3000)
    return () => clearTimeout(t)
  }, [confirming])

  const title = s.title ?? 'New conversation'

  if (editing) {
    return (
      <li>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            const v = input.current?.value.trim()
            if (v && v !== s.title) rename.mutate(v)
            setEditing(false)
          }}
        >
          <input
            ref={input}
            defaultValue={title}
            maxLength={200}
            onBlur={(e) => e.currentTarget.form?.requestSubmit()}
            onKeyDown={(e) => e.key === 'Escape' && setEditing(false)}
            aria-label="Conversation name"
            className="h-[52px] w-full rounded-lg border border-accent bg-bg px-2.5 text-fg outline-none"
          />
        </form>
      </li>
    )
  }

  return (
    <li className="group relative">
      <Tooltip
        content={title}
        when={() => !!titleRef.current && titleRef.current.scrollWidth > titleRef.current.clientWidth}
      >
        <button
          onClick={onOpen}
          onDoubleClick={() => setEditing(true)}
          aria-current={active ? 'page' : undefined}
          className={`flex w-full flex-col rounded-lg px-2.5 py-1.5 pr-16 text-left ${
            active ? 'bg-surface text-fg' : 'text-fg/85 hover:bg-surface/60'
          }`}
        >
          <span ref={titleRef} className="truncate">{title}</span>
          <span className="truncate text-[12px] leading-4 text-muted">{s.document_title}</span>
        </button>
      </Tooltip>
      <div
        className={`absolute right-1.5 top-1/2 flex -translate-y-1/2 items-center gap-0.5 ${
          confirming ? '' : 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100'
        }`}
      >
        {confirming ? (
          <button
            onClick={() => remove.mutate()}
            className="h-7 rounded-md bg-danger px-2 text-[12px] font-medium text-white"
            aria-label={`Confirm delete ${title}`}
          >
            Delete
          </button>
        ) : (
          <>
            <button
              onClick={() => setEditing(true)}
              className="grid size-7 place-items-center rounded-md text-muted hover:bg-line hover:text-fg"
              aria-label={`Rename ${title}`}
            >
              <Pencil size={13} />
            </button>
            <button
              onClick={() => setConfirming(true)}
              className="grid size-7 place-items-center rounded-md text-muted hover:bg-line hover:text-danger"
              aria-label={`Delete ${title}`}
            >
              <Trash2 size={13} />
            </button>
          </>
        )}
      </div>
    </li>
  )
}
