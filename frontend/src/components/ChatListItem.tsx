/** Элемент списка чатов: название, превью последнего сообщения, unread. */

import { useQuery } from '@tanstack/react-query'
import { NavLink } from 'react-router-dom'
import { chatsApi } from '@/api/client'
import type { Chat } from '@/api/types'
import { chatTitle, initials } from '@/lib/format'

export function ChatListItem({ chat, meId }: { chat: Chat; meId: string }) {
  // участники нужны для имени direct-чата; details кэшируются и для ChatPage
  const details = useQuery({ queryKey: ['chat', chat.id], queryFn: () => chatsApi.get(chat.id) })

  const title = chatTitle(
    { type: chat.type, title: chat.title, members: details.data?.members },
    meId,
  )

  return (
    <NavLink
      to={`/chat/${chat.id}`}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-lg px-3 py-2 transition-colors ${
          isActive ? 'bg-panel-2' : 'hover:bg-panel-2/60'
        }`
      }
    >
      <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-accent text-sm font-semibold text-white">
        {initials(title)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-sm font-medium">{title}</span>
          {chat.last_message_at && (
            <span className="shrink-0 text-[11px] text-muted">
              {new Date(chat.last_message_at).toLocaleDateString(undefined, {
                day: 'numeric',
                month: 'short',
              })}
            </span>
          )}
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-xs text-muted">
            {chat.type === 'group' && <span className="mr-1 text-[10px]">ГРУППА</span>}
          </span>
          {chat.unread_count > 0 && (
            <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-accent text-[11px] font-semibold text-white">
              {chat.unread_count}
            </span>
          )}
        </div>
      </div>
    </NavLink>
  )
}
