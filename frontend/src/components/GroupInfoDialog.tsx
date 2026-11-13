/** Диалог информации о группе (этап 12): переименование, участники, роли, добавление, исключение, владение. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Crown, Search, Shield, UserPlus, X } from 'lucide-react'
import { useState } from 'react'
import { chatsApi, usersApi } from '@/api/client'
import type { ChatDetails } from '@/api/types'
import { initials, userLabel } from '@/lib/format'

interface Props {
  chat: ChatDetails
  meId: string
  onClose: () => void
}

const ROLE_LABEL: Record<string, string> = {
  owner: 'владелец',
  admin: 'админ',
  member: 'участник',
}

export function GroupInfoDialog({ chat, meId, onClose }: Props) {
  const queryClient = useQueryClient()
  const [title, setTitle] = useState(chat.title ?? '')
  const [adding, setAdding] = useState(false)
  const [q, setQ] = useState('')

  const myRole = chat.members.find((m) => m.user_id === meId)?.role
  const isOwner = myRole === 'owner'
  const isAdmin = myRole === 'owner' || myRole === 'admin'

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['chat', chat.id] })
    void queryClient.invalidateQueries({ queryKey: ['chats'] })
  }

  const rename = useMutation({
    mutationFn: () => chatsApi.rename(chat.id, title.trim()),
    onSuccess: invalidate,
  })

  const addMembers = useMutation({
    mutationFn: (ids: string[]) => chatsApi.addMembers(chat.id, ids),
    onSuccess: () => {
      setAdding(false)
      setQ('')
      invalidate()
    },
  })

  const removeMember = useMutation({
    mutationFn: (userId: string) => chatsApi.removeMember(chat.id, userId),
    onSuccess: invalidate,
  })

  const setRole = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: 'admin' | 'member' }) =>
      chatsApi.setMemberRole(chat.id, userId, role),
    onSuccess: invalidate,
  })

  const transferOwner = useMutation({
    mutationFn: (userId: string) => chatsApi.transferOwnership(chat.id, userId),
    onSuccess: invalidate,
  })

  const found = useQuery({
    queryKey: ['users', q],
    queryFn: () => usersApi.search(q),
    enabled: adding && q.length >= 1,
  })

  const memberIds = new Set(chat.members.map((m) => m.user_id))
  const candidates = (found.data ?? []).filter((u) => !memberIds.has(u.id))

  const canModerate = (role: string) => role !== 'owner' && (isOwner || (isAdmin && role === 'member'))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="flex max-h-[85vh] w-[440px] flex-col rounded-xl border border-border bg-panel p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">Информация о группе</h2>
          <button onClick={onClose} className="rounded p-1 text-muted hover:bg-panel-2">
            <X className="size-4" />
          </button>
        </div>

        {/* Название */}
        <div className="mb-4">
          <div className="mb-1 text-xs text-muted">Название</div>
          <div className="flex gap-2">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              disabled={!isAdmin}
              className="flex-1 rounded-lg border border-border bg-panel-2 px-3 py-2 text-sm outline-none focus:border-accent disabled:opacity-50"
            />
            {isAdmin && title.trim() !== chat.title && title.trim() !== '' && (
              <button
                onClick={() => rename.mutate()}
                disabled={rename.isPending}
                className="rounded-lg bg-accent px-3 text-sm text-white hover:bg-accent-hover disabled:opacity-40"
              >
                Сохранить
              </button>
            )}
          </div>
        </div>

        {/* Участники */}
        <div className="mb-2 flex items-center justify-between">
          <div className="text-xs text-muted">Участники ({chat.members.length})</div>
          {isAdmin && (
            <button
              onClick={() => {
                setAdding((v) => {
                  if (v) setQ('')
                  return !v
                })
              }}
              className="flex items-center gap-1 rounded px-2 py-0.5 text-xs text-accent hover:bg-panel-2"
            >
              <UserPlus className="size-3.5" /> Добавить
            </button>
          )}
        </div>

        {adding && (
          <div className="mb-3">
            <div className="relative mb-2">
              <Search className="absolute left-3 top-2.5 size-4 text-muted" />
              <input
                autoFocus
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Поиск пользователей…"
                className="w-full rounded-lg border border-border bg-panel-2 py-2 pl-9 pr-3 text-sm outline-none focus:border-accent"
              />
            </div>
            <div className="max-h-40 overflow-y-auto rounded-lg border border-border">
              {candidates.map((u) => (
                <button
                  key={u.id}
                  onClick={() => addMembers.mutate([u.id])}
                  disabled={addMembers.isPending}
                  className="flex w-full items-center gap-2 px-2 py-2 text-left hover:bg-panel-2 disabled:opacity-50"
                >
                  <div className="flex size-7 items-center justify-center rounded-full bg-accent text-[10px] font-semibold text-white">
                    {initials(userLabel(u))}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm">{userLabel(u)}</div>
                    <div className="truncate text-xs text-muted">@{u.username} {u.is_bot && '· бот'}</div>
                  </div>
                  <UserPlus className="size-4 text-accent" />
                </button>
              ))}
              {q.length >= 1 && !found.isLoading && candidates.length === 0 && (
                <div className="px-2 py-2 text-xs text-muted">Никого не найдено</div>
              )}
            </div>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto">
          {chat.members.map((m) => {
            const u = m.user
            const moddable = canModerate(m.role)
            const roleMutable = isOwner && m.user_id !== meId && m.role !== 'owner'
            return (
              <div key={m.user_id} className="flex items-center gap-2 rounded-lg px-1 py-1.5 hover:bg-panel-2">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold text-white">
                  {initials(userLabel(u))}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm">
                    {userLabel(u)}
                    {m.user_id === meId && <span className="ml-1 text-xs text-muted">· вы</span>}
                  </div>
                  <div className="truncate text-xs text-muted">{u ? `@${u.username}` : m.user_id}</div>
                </div>

                {/* Роль + управление */}
                <div className="flex shrink-0 items-center gap-1">
                  <span
                    className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] ${
                      m.role === 'owner' ? 'bg-accent/30 text-accent' : m.role === 'admin' ? 'bg-panel-2 text-foreground' : 'text-muted'
                    }`}
                    title={ROLE_LABEL[m.role]}
                  >
                    {m.role === 'owner' ? <Crown className="size-3" /> : m.role === 'admin' ? <Shield className="size-3" /> : null}
                    {ROLE_LABEL[m.role]}
                  </span>
                  {moddable && (
                    <button
                      title="Исключить"
                      onClick={() => removeMember.mutate(m.user_id)}
                      disabled={removeMember.isPending}
                      className="rounded p-1 text-muted hover:bg-panel-2 hover:text-red-400"
                    >
                      <X className="size-3.5" />
                    </button>
                  )}
                  {roleMutable && (
                    <select
                      value={m.role}
                      onChange={(e) => setRole.mutate({ userId: m.user_id, role: e.target.value as 'admin' | 'member' })}
                      disabled={setRole.isPending}
                      className="rounded border border-border bg-panel-2 px-1 py-0.5 text-[11px] outline-none"
                      title="Изменить роль"
                    >
                      <option value="member">участник</option>
                      <option value="admin">админ</option>
                    </select>
                  )}
                  {isOwner && m.user_id !== meId && m.role !== 'owner' && (
                    <button
                      title="Передать владение"
                      onClick={() => {
                        if (confirm(`Передать владение группой пользователю ${userLabel(u)}?`)) {
                          transferOwner.mutate(m.user_id)
                        }
                      }}
                      disabled={transferOwner.isPending}
                      className="rounded p-1 text-muted hover:bg-panel-2 hover:text-accent"
                    >
                      <Crown className="size-3.5" />
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
