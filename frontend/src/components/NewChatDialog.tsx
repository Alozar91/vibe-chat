/** Диалог создания чата: direct (поиск пользователя) или группа (название + участники). */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { chatsApi, usersApi } from '@/api/client'
import type { User } from '@/api/types'
import { initials, userLabel } from '@/lib/format'

interface Props {
  open: boolean
  onClose: () => void
}

export function NewChatDialog({ open, onClose }: Props) {
  const [mode, setMode] = useState<'direct' | 'group'>('direct')
  const [q, setQ] = useState('')
  const [title, setTitle] = useState('')
  const [selected, setSelected] = useState<User[]>([])
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const found = useQuery({
    queryKey: ['users', q],
    queryFn: () => usersApi.search(q),
    enabled: open && q.length >= 1,
  })

  const createDirect = useMutation({
    mutationFn: (userId: string) => chatsApi.createDirect(userId),
    onSuccess: (chat) => {
      void queryClient.invalidateQueries({ queryKey: ['chats'] })
      onClose()
      navigate(`/chat/${chat.id}`)
    },
  })

  const createGroup = useMutation({
    mutationFn: () => chatsApi.createGroup(title, selected.map((u) => u.id)),
    onSuccess: (chat) => {
      void queryClient.invalidateQueries({ queryKey: ['chats'] })
      onClose()
      navigate(`/chat/${chat.id}`)
    },
  })

  useEffect(() => {
    if (open) {
      setMode('direct')
      setQ('')
      setTitle('')
      setSelected([])
    }
  }, [open])

  if (!open) return null

  const toggleUser = (u: User) => {
    setSelected((prev) => (prev.some((s) => s.id === u.id) ? prev.filter((s) => s.id !== u.id) : [...prev, u]))
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="w-[420px] rounded-xl border border-border bg-panel p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">Новый чат</h2>
          <button onClick={onClose} className="rounded p-1 text-muted hover:bg-panel-2">
            <X className="size-4" />
          </button>
        </div>

        <div className="mb-3 flex gap-2 text-sm">
          <button
            onClick={() => setMode('direct')}
            className={`flex-1 rounded-lg px-3 py-1.5 ${mode === 'direct' ? 'bg-accent text-white' : 'bg-panel-2 text-muted'}`}
          >
            Личный
          </button>
          <button
            onClick={() => setMode('group')}
            className={`flex-1 rounded-lg px-3 py-1.5 ${mode === 'group' ? 'bg-accent text-white' : 'bg-panel-2 text-muted'}`}
          >
            Группа
          </button>
        </div>

        {mode === 'group' && (
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Название группы"
            className="mb-3 w-full rounded-lg border border-border bg-panel-2 px-3 py-2 text-sm outline-none focus:border-accent"
          />
        )}

        {mode === 'group' && selected.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-1">
            {selected.map((u) => (
              <span
                key={u.id}
                className="flex items-center gap-1 rounded-full bg-panel-2 px-2 py-0.5 text-xs"
              >
                {userLabel(u)}
                <button onClick={() => toggleUser(u)}>
                  <X className="size-3" />
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="relative mb-2">
          <Search className="absolute left-3 top-2.5 size-4 text-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Поиск людей и ботов…"
            className="w-full rounded-lg border border-border bg-panel-2 py-2 pl-9 pr-3 text-sm outline-none focus:border-accent"
          />
        </div>

        <div className="max-h-64 overflow-y-auto">
          {(found.data ?? []).map((u) => {
            const isSelected = selected.some((s) => s.id === u.id)
            return (
              <button
                key={u.id}
                onClick={() => (mode === 'direct' ? createDirect.mutate(u.id) : toggleUser(u))}
                className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left hover:bg-panel-2"
              >
                <div className="flex size-8 items-center justify-center rounded-full bg-accent text-xs font-semibold text-white">
                  {initials(userLabel(u))}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm">{userLabel(u)}</div>
                  <div className="truncate text-xs text-muted">
                    @{u.username} {u.is_bot && '· бот'}
                  </div>
                </div>
                {mode === 'group' && isSelected && <span className="text-accent">✓</span>}
              </button>
            )
          })}
          {q.length >= 1 && !found.isLoading && (found.data ?? []).length === 0 && (
            <div className="px-2 py-3 text-sm text-muted">Никого не найдено</div>
          )}
        </div>

        {mode === 'group' && (
          <button
            disabled={!title.trim() || selected.length === 0 || createGroup.isPending}
            onClick={() => createGroup.mutate()}
            className="mt-3 w-full rounded-lg bg-accent py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-40"
          >
            {createGroup.isPending ? 'Создание…' : 'Создать группу'}
          </button>
        )}
      </div>
    </div>
  )
}
