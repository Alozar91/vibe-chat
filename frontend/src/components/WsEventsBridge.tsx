/** WS-события → TanStack Query cache (§9): точечные обновления, дедупликация по id. */

import type { QueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useWsStore } from '@/realtime/ws'
import type { Chat, Message, ReactionGroup } from '@/api/types'

interface ReactionPayload {
  message_id: string
  chat_id: string
  reactions: ReactionGroup[]
}

/** Мерж сообщения в ленту: только в уже загруженную (REST догонит при открытии чата). */
function upsertMessage(queryClient: QueryClient, chatId: string, msg: Message): void {
  const key = ['messages', chatId, 'list'] as const
  const existing = queryClient.getQueryData<Message[]>(key)
  if (existing === undefined) return
  const idx = existing.findIndex((m) => m.id === msg.id)
  if (idx >= 0) {
    const next = existing.slice()
    next[idx] = msg
    queryClient.setQueryData(key, next)
  } else {
    queryClient.setQueryData(key, [...existing, msg])
  }
}

export function WsEventsBridge({ queryClient }: { queryClient: QueryClient }) {
  const onEvent = useWsStore((s) => s.onEvent)

  useEffect(() => {
    const unsub = onEvent((e) => {
      switch (e.type) {
        case 'message.new':
        case 'message.edited':
        case 'message.deleted': {
          // бэкенд шлёт полную сериализацию MessageOut (§9, этап 10.2)
          const msg = (e.data as { message?: Message }).message
          if (!msg || !msg.id || !msg.created_at || !msg.updated_at) return
          upsertMessage(queryClient, msg.chat_id, msg)
          if (e.type === 'message.new') {
            void queryClient.invalidateQueries({ queryKey: ['chats'] })
          }
          break
        }
        case 'reaction.updated': {
          const { message_id, chat_id, reactions } = e.data as ReactionPayload
          queryClient.setQueryData<Message[]>(['messages', chat_id, 'list'], (old) => {
            if (!old) return old
            const idx = old.findIndex((m) => m.id === message_id)
            if (idx < 0) return old
            const next = old.slice()
            next[idx] = { ...next[idx], reactions }
            return next
          })
          break
        }
        case 'chat.created': {
          // новый чат (в т.ч. созданный собеседником): список догонит REST
          void queryClient.invalidateQueries({ queryKey: ['chats'] })
          break
        }
        case 'chat.updated': {
          const { chat, deleted } = e.data as { chat: Chat; deleted?: boolean }
          queryClient.setQueryData<Chat>(['chat', chat.id], (old) =>
            old ? { ...old, ...chat, unread_count: old.unread_count } : old,
          )
          void queryClient.invalidateQueries({ queryKey: ['chats'] })
          if (deleted) void queryClient.removeQueries({ queryKey: ['chat', chat.id] })
          break
        }
        case 'member.joined':
        case 'member.left': {
          // изменение состава (этап 12): publish_chat_event шлёт {chat: ChatOut, user_id}
          const { chat } = e.data as { chat?: Chat }
          if (chat?.id) void queryClient.invalidateQueries({ queryKey: ['chat', chat.id] })
          void queryClient.invalidateQueries({ queryKey: ['chats'] })
          break
        }
        case 'read': {
          const { chat_id, user_id, last_read_message_id } = e.data as {
            chat_id: string
            user_id: string
            last_read_message_id: string
          }
          queryClient.setQueryData(['chat', chat_id], (old: unknown) => {
            const details = old as
              | { members: { user_id: string; last_read_message_id: string | null }[] }
              | undefined
            if (!details) return old
            return {
              ...details,
              members: details.members.map((m) =>
                m.user_id === user_id ? { ...m, last_read_message_id: last_read_message_id } : m,
              ),
            }
          })
          break
        }
        default:
          break
      }
    })
    return unsub
  }, [onEvent, queryClient])

  return null
}
