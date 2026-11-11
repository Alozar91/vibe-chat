/** Лента чата: сообщения, реакции, цитирование, typing, отправка (§7, §9). */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Paperclip, Send, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { chatsApi, messagesApi, usersApi } from '@/api/client'
import type { Message } from '@/api/types'
import { MessageBubble } from '@/components/MessageBubble'
import { useWsStore } from '@/realtime/ws'
import { sendTyping } from '@/realtime/ws'
import { browserTimezone, chatTitle, initials, userLabel } from '@/lib/format'

const EMOJI_SET = [
  ['thumbs_up', '👍'],
  ['heart', '❤️'],
  ['laugh', '😂'],
  ['fire', '🔥'],
  ['check', '✅'],
] as const

/** Троттлинг typing-событий: не чаще раза в 2 сек (§16 лимиты). */
let lastTypingSent = 0
function maybeSendTyping(chatId: string): void {
  const now = Date.now()
  if (now - lastTypingSent < 2000) return
  lastTypingSent = now
  sendTyping(chatId)
}

/** Панель эмодзи-реакций (§6): 5 фиксированных. */
export function ReactionBar({
  onPick,
  onClose,
}: {
  onPick: (emoji: string) => void
  onClose: () => void
}) {
  return (
    <div className="absolute bottom-full right-0 z-10 mb-1 flex gap-1 rounded-lg border border-border bg-panel px-2 py-1.5 shadow-lg">
      {EMOJI_SET.map(([name, char]) => (
        <button
          key={name}
          onClick={() => {
            onPick(name)
            onClose()
          }}
          className="rounded p-1 text-lg hover:bg-panel-2"
          title={name}
        >
          {char}
        </button>
      ))}
    </div>
  )
}

export function ChatPage() {
  const { chatId } = useParams()
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const [replyTo, setReplyTo] = useState<Message | null>(null)
  const [editing, setEditing] = useState<Message | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const lastReadRef = useRef<string | null>(null)

  const me = useQuery({ queryKey: ['me'], queryFn: usersApi.me })

  // без chatId — пустой экран-заглушка (выбор чата)
  const chatDetails = useQuery({
    queryKey: ['chat', chatId],
    queryFn: () => chatsApi.get(chatId!),
    enabled: !!chatId,
  })
  const messages = useQuery({
    queryKey: ['messages', chatId, 'list'],
    queryFn: () => messagesApi.list(chatId!, { limit: 50 }),
    enabled: !!chatId,
  })

  const typing = useWsStore((s) => s.typing)
  const online = useWsStore((s) => s.online)

  const send = useMutation({
    mutationFn: (payload: { text: string }) => {
      const clientRef = crypto.randomUUID()
      return messagesApi.send(
        chatId!,
        {
          text: payload.text,
          reply_to_id: replyTo?.id,
          client_ref: clientRef,
          timezone: browserTimezone(),
        },
        clientRef,
      )
    },
    onSuccess: (msg) => {
      queryClient.setQueryData<Message[]>(['messages', chatId, 'list'], (old) => {
        const list = old ?? []
        // убираем оптимистичный дубль по client_ref
        const cleaned = list.filter(
          (m) => !(m.client_ref && msg.client_ref && m.client_ref === msg.client_ref && m.id.startsWith('temp-')),
        )
        if (cleaned.some((m) => m.id === msg.id)) return cleaned
        return [...cleaned, msg]
      })
      void queryClient.invalidateQueries({ queryKey: ['chats'] })
    },
  })

  const editMsg = useMutation({
    mutationFn: ({ id, text: t }: { id: string; text: string }) => messagesApi.edit(id, t),
    onSuccess: (msg) => {
      queryClient.setQueryData<Message[]>(['messages', chatId, 'list'], (old) =>
        (old ?? []).map((m) => (m.id === msg.id ? msg : m)),
      )
      setEditing(null)
    },
  })

  const read = useMutation({
    mutationFn: (messageId: string) => chatsApi.read(chatId!, messageId),
  })

  const sorted = useMemo(
    () => [...(messages.data ?? [])].sort((a, b) => (a.id < b.id ? -1 : 1)),
    [messages.data],
  )

  // автоскролл вниз на новых сообщениях
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [sorted.length])

  // read receipt: последнее видимое сообщение (после загрузки ленты)
  useEffect(() => {
    if (!chatId || sorted.length === 0) return
    const lastId = sorted[sorted.length - 1].id
    if (lastReadRef.current === lastId) return
    lastReadRef.current = lastId
    read.mutate(lastId)
    void queryClient.invalidateQueries({ queryKey: ['chats'] })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, sorted.length])

  if (!chatId) {
    return (
      <div className="flex h-full flex-1 items-center justify-center text-muted">
        Выберите чат слева или создайте новый
      </div>
    )
  }

  const meId = me.data?.id ?? ''
  const members = chatDetails.data?.members ?? []
  const usersById = new Map(members.map((m) => [m.user_id, m.user]))

  const typingUsers = Object.entries(typing[chatId] ?? {})
    .filter(([uid]) => uid !== meId)
    .map(([uid]) => userLabel(usersById.get(uid)))

  const title = chatTitle(
    { type: chatDetails.data?.type ?? 'group', title: chatDetails.data?.title ?? null, members },
    meId,
  )

  const handleSend = () => {
    const t = text.trim()
    if (!t) return
    if (editing) {
      editMsg.mutate({ id: editing.id, text: t })
      setText('')
      return
    }
    send.mutate({ text: t })
    setText('')
    setReplyTo(null)
  }

  return (
    <div className="flex h-full flex-1 flex-col">
      {/* Шапка чата */}
      <header className="flex items-center gap-3 border-b border-border bg-panel px-4 py-3">
        <div className="flex size-9 items-center justify-center rounded-full bg-accent text-sm font-semibold text-white">
          {initials(title)}
        </div>
        <div>
          <div className="text-sm font-semibold">{title}</div>
          <div className="text-xs text-muted">
            {chatDetails.data?.type === 'group'
              ? `${members.length} участников`
              : Object.entries(online).find(([uid]) => uid !== meId)?.[1].online
                ? 'в сети'
                : 'не в сети'}
          </div>
        </div>
      </header>

      {/* Лента */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {messages.isLoading ? (
          <div className="text-sm text-muted">Загрузка…</div>
        ) : sorted.length === 0 ? (
          <div className="text-sm text-muted">Сообщений пока нет. Напишите первое!</div>
        ) : (
          sorted.map((m) => (
            <MessageBubble
              key={m.id}
              message={m}
              isMine={m.sender_id === meId}
              myId={meId}
              sender={usersById.get(m.sender_id ?? '')}
              timeDisplay={me.data?.time_display ?? 'browser'}
              fixedTz={me.data?.timezone ?? null}
              replyTarget={sorted.find((x) => x.id === m.reply_to_id)}
              onReply={() => {
                setReplyTo(m)
                setEditing(null)
              }}
              onEdit={() => {
                setEditing(m)
                setText(m.text ?? '')
                setReplyTo(null)
              }}
            />
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* Typing-индикатор */}
      <div className="h-5 px-4 text-xs text-muted">
        {typingUsers.length > 0 && `${typingUsers.join(', ')} печатает…`}
      </div>

      {/* Плашки reply/edit */}
      {(replyTo || editing) && (
        <div className="mx-4 mb-1 flex items-center gap-2 rounded-lg border-l-2 border-accent bg-panel-2 px-3 py-1.5 text-xs">
          <span className="text-accent">{editing ? 'Редактирование' : 'Ответ на'}</span>
          <span className="min-w-0 flex-1 truncate text-muted">
            {(editing ?? replyTo)?.text ?? 'вложение'}
          </span>
          <button
            onClick={() => {
              setReplyTo(null)
              if (editing) {
                setEditing(null)
                setText('')
              }
            }}
          >
            <X className="size-3.5" />
          </button>
        </div>
      )}

      {/* Композер */}
      <div className="flex items-end gap-2 border-t border-border bg-panel px-4 py-3">
        <button title="Вложения (скоро)" className="rounded p-2 text-muted hover:bg-panel-2" disabled>
          <Paperclip className="size-5" />
        </button>
        <textarea
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            maybeSendTyping(chatId)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
          placeholder="Сообщение… (Enter — отправить, Shift+Enter — новая строка)"
          rows={1}
          className="max-h-32 min-h-[40px] flex-1 resize-none rounded-lg border border-border bg-panel-2 px-3 py-2 text-sm outline-none focus:border-accent"
        />
        <button
          onClick={handleSend}
          disabled={!text.trim() || send.isPending}
          className="rounded-lg bg-accent p-2.5 text-white hover:bg-accent-hover disabled:opacity-40"
        >
          <Send className="size-5" />
        </button>
      </div>
    </div>
  )
}
