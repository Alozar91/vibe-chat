/** WS-события → TanStack Query cache (§9): точечные обновления, дедупликация по id. */

import type { QueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useWsStore } from '@/realtime/ws'
import type { Message, ReactionGroup } from '@/api/types'

function upsertMessage(list: Message[] | undefined, msg: Message): Message[] {
  const list0 = list ?? []
  const idx = list0.findIndex((m) => m.id === msg.id)
  if (idx >= 0) {
    const next = list0.slice()
    next[idx] = msg
    return next
  }
  return [...list0, msg]
}

interface MessagePayload {
  message: Message
}
interface ReactionPayload {
  message_id: string
  chat_id: string
  reactions: ReactionGroup[]
}

export function WsEventsBridge({ queryClient }: { queryClient: QueryClient }) {
  const onEvent = useWsStore((s) => s.onEvent)

  useEffect(() => {
    const unsub = onEvent((e) => {
      switch (e.type) {
        case 'message.new':
        case 'message.edited':
        case 'message.deleted': {
          const msg = (e.data as MessagePayload).message
          queryClient.setQueryData<Message[]>(['messages', msg.chat_id, 'list'], (old) =>
            upsertMessage(old, msg),
          )
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
        case 'chat.created':
        case 'chat.updated':
        case 'member.joined':
        case 'member.left':
          void queryClient.invalidateQueries({ queryKey: ['chats'] })
          break
        default:
          break
      }
    })
    return unsub
  }, [onEvent, queryClient])

  return null
}
