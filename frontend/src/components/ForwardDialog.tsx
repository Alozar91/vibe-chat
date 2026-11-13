/** Диалог пересылки сообщения (этап 12): мультивыбор чатов → POST /messages/{id}/forward. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useState } from 'react'
import { chatsApi, messagesApi } from '@/api/client'
import type { Chat, Message } from '@/api/types'
import { chatTitle, initials } from '@/lib/format'

interface Props {
  message: Message
  meId: string
  onClose: () => void
}

/** Заголовок чата в диалоге: group — title, direct — имя через details-кэш (как ChatListItem). */
function ChatRow({
  chat,
  meId,
  selected,
  onToggle,
}: {
  chat: Chat
  meId: string
  selected: boolean
  onToggle: () => void
}) {
  // детали (участники) нужны для имени direct-чата; кэш общий с sidebar/ChatPage
  const details = useQuery({ queryKey: ['chat', chat.id], queryFn: () => chatsApi.get(chat.id) })
  const title = chatTitle({ type: chat.type, title: chat.title, members: details.data?.members }, meId)

  return (
    <button
      onClick={onToggle}
      className={`flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left ${
        selected ? 'bg-accent/10' : 'hover:bg-panel-2'
      }`}
    >
      <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold text-white">
        {initials(title)}
      </div>
      <div className="min-w-0 flex-1 truncate text-sm">
        {title}
        {chat.type === 'group' && <span className="ml-1 text-[10px] text-muted">ГРУППА</span>}
      </div>
      {selected && <span className="shrink-0 text-accent">✓</span>}
    </button>
  )
}

export function ForwardDialog({ message, meId, onClose }: Props) {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string[]>([])

  const chats = useQuery({ queryKey: ['chats'], queryFn: chatsApi.list })

  const forward = useMutation({
    mutationFn: () => messagesApi.forward(message.id, selected),
    onSuccess: () => {
      // ленты целевых чатов догрузятся при открытии; списки — обновить
      void queryClient.invalidateQueries({ queryKey: ['chats'] })
      onClose()
    },
  })

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]))

  const list = (chats.data ?? []).filter((c) => c.id !== message.chat_id)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="flex max-h-[70vh] w-[400px] flex-col rounded-xl border border-border bg-panel p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">Переслать сообщение</h2>
          <button onClick={onClose} className="rounded p-1 text-muted hover:bg-panel-2">
            <X className="size-4" />
          </button>
        </div>

        <div className="mb-2 truncate rounded-lg bg-panel-2 px-3 py-2 text-xs text-muted">
          {message.text || 'вложение'}
        </div>

        <div className="mb-3 min-h-0 flex-1 overflow-y-auto">
          {chats.isLoading && <div className="px-2 py-3 text-sm text-muted">Загрузка…</div>}
          {list.length === 0 && !chats.isLoading && (
            <div className="px-2 py-3 text-sm text-muted">Нет других чатов</div>
          )}
          {list.map((c) => (
            <ChatRow
              key={c.id}
              chat={c}
              meId={meId}
              selected={selected.includes(c.id)}
              onToggle={() => toggle(c.id)}
            />
          ))}
        </div>

        <button
          disabled={selected.length === 0 || forward.isPending}
          onClick={() => forward.mutate()}
          className="w-full rounded-lg bg-accent py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-40"
        >
          {forward.isPending
            ? 'Пересылка…'
            : selected.length > 0
              ? `Переслать (${selected.length})`
              : 'Выберите чаты'}
        </button>
      </div>
    </div>
  )
}
