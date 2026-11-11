/** Layout мессенджера: сайдбар чатов + контент (роут-выход). */

import { useMutation, useQuery } from '@tanstack/react-query'
import { LogOut, MessageSquare, Plus, Settings } from 'lucide-react'
import { useState } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from 'react-oidc-context'
import { chatsApi, usersApi } from '@/api/client'
import type { Chat, User } from '@/api/types'
import { ChatListItem } from '@/components/ChatListItem'
import { NewChatDialog } from '@/components/NewChatDialog'
import { useWsStore } from '@/realtime/ws'
import { initials } from '@/lib/format'

export function ChatsLayout() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [newChatOpen, setNewChatOpen] = useState(false)
  const status = useWsStore((s) => s.status)

  const me = useQuery({ queryKey: ['me'], queryFn: usersApi.me })
  const chats = useQuery({ queryKey: ['chats'], queryFn: chatsApi.list })

  const logout = useMutation({
    mutationFn: async () => {
      await auth.signoutRedirect()
    },
  })

  const meUser: User | undefined = me.data
  const unreadTotal = (chats.data ?? []).reduce((acc, c: Chat) => acc + c.unread_count, 0)

  return (
    <div className="flex h-full">
      <aside className="flex w-72 shrink-0 flex-col border-r border-border bg-panel">
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <MessageSquare className="size-5 text-accent" />
          <span className="text-lg font-semibold">Vibe Chat</span>
          <span
            title={`WS: ${status}`}
            className={`ml-auto size-2 rounded-full ${status === 'open' ? 'bg-emerald-500' : 'bg-amber-500'}`}
          />
        </div>

        <button
          onClick={() => setNewChatOpen(true)}
          className="mx-3 mt-3 flex items-center gap-2 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-hover"
        >
          <Plus className="size-4" /> Новый чат
        </button>

        <nav className="mt-2 flex-1 overflow-y-auto px-2 pb-2">
          {chats.isLoading ? (
            <div className="px-3 py-2 text-sm text-muted">Загрузка…</div>
          ) : (chats.data ?? []).length === 0 ? (
            <div className="px-3 py-2 text-sm text-muted">Чатов нет. Создайте первый!</div>
          ) : (
            (chats.data ?? []).map((c: Chat) => (
              <ChatListItem key={c.id} chat={c} meId={meUser?.id ?? ''} />
            ))
          )}
        </nav>

        <div className="border-t border-border p-3">
          <div className="flex items-center gap-2">
            <div className="flex size-9 items-center justify-center rounded-full bg-accent text-sm font-semibold text-white">
              {meUser ? initials(meUser.display_name) : '…'}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{meUser?.display_name ?? '…'}</div>
              <div className="truncate text-xs text-muted">@{meUser?.username ?? ''}</div>
            </div>
            <button
              title="Настройки"
              onClick={() => navigate('/settings')}
              className="rounded-md p-2 text-muted hover:bg-panel-2 hover:text-text"
            >
              <Settings className="size-4" />
            </button>
            <button
              title="Выйти"
              onClick={() => logout.mutate()}
              className="rounded-md p-2 text-muted hover:bg-panel-2 hover:text-text"
            >
              <LogOut className="size-4" />
            </button>
          </div>
          {unreadTotal > 0 && (
            <div className="mt-2 text-center text-xs text-muted">Непрочитанных: {unreadTotal}</div>
          )}
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <Outlet />
      </main>

      <NewChatDialog open={newChatOpen} onClose={() => setNewChatOpen(false)} />
    </div>
  )
}
