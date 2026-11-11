/** WS-состояние (§9): соединение, живые события, typing, presence — Zustand. */

import { create } from 'zustand'
import { getAccessToken } from '@/auth/oidc'
import type { WsEvent } from '@/api/types'

export type ConnStatus = 'connecting' | 'open' | 'closed'

interface WsState {
  status: ConnStatus
  typing: Record<string, Record<string, number>> // chat_id → user_id → ts последнего typing
  online: Record<string, { online: boolean; last_seen_at: string | null }>
  handlers: Set<(e: WsEvent) => void>
  setStatus: (s: ConnStatus) => void
  onEvent: (h: (e: WsEvent) => void) => () => void
  setTyping: (chatId: string, userId: string) => void
  setPresence: (userId: string, online: boolean, lastSeen: string | null) => void
  expireTyping: () => void
}

export const useWsStore = create<WsState>((set, get) => ({
  status: 'closed',
  typing: {},
  online: {},
  handlers: new Set(),
  setStatus: (s) => set({ status: s }),
  onEvent: (h) => {
    get().handlers.add(h)
    return () => {
      get().handlers.delete(h)
    }
  },
  setTyping: (chatId, userId) =>
    set((st) => ({
      typing: {
        ...st.typing,
        [chatId]: { ...(st.typing[chatId] ?? {}), [userId]: Date.now() },
      },
    })),
  setPresence: (userId, online, lastSeen) =>
    set((st) => ({ online: { ...st.online, [userId]: { online, last_seen_at: lastSeen } } })),
  expireTyping: () => {
    const cutoff = Date.now() - 5000
    set((st) => {
      const next: typeof st.typing = {}
      let changed = false
      for (const [chatId, users] of Object.entries(st.typing)) {
        const alive: Record<string, number> = {}
        for (const [uid, ts] of Object.entries(users)) {
          if (ts > cutoff) alive[uid] = ts
          else changed = true
        }
        if (Object.keys(alive).length) next[chatId] = alive
      }
      return changed ? { typing: next } : {}
    })
  },
}))

/** Подключение с ticket-обменом (§5 WS auth) и reconnect с backoff. */
let socket: WebSocket | null = null
let reconnectAttempt = 0
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let closedByUs = false

export async function connectWs(): Promise<void> {
  if (socket && socket.readyState <= WebSocket.OPEN) return
  closedByUs = false
  const store = useWsStore.getState()
  store.setStatus('connecting')
  try {
    const resp = await fetch('/api/v1/ws/ticket', {
      method: 'POST',
      headers: { Authorization: `Bearer ${getAccessToken()}` },
    })
    if (!resp.ok) throw new Error(`ticket ${resp.status}`)
    const { ticket } = (await resp.json()) as { ticket: string }

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${proto}//${window.location.host}/api/v1/ws?ticket=${ticket}`)
    socket = ws

    ws.onopen = () => {
      reconnectAttempt = 0
      useWsStore.getState().setStatus('open')
    }
    ws.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data as string) as WsEvent
        const data = event.data as Record<string, string | boolean | null>
        if (event.type === 'typing') {
          useWsStore.getState().setTyping(String(data.chat_id), String(data.user_id))
        } else if (event.type === 'presence') {
          useWsStore
            .getState()
            .setPresence(
              String(data.user_id),
              Boolean(data.online),
              data.last_seen_at !== null && data.last_seen_at !== undefined ? String(data.last_seen_at) : null,
            )
        }
        for (const h of useWsStore.getState().handlers) h(event)
      } catch {
        // не-JSON кадр — игнорируем
      }
    }
    ws.onclose = () => {
      socket = null
      useWsStore.getState().setStatus('closed')
      if (!closedByUs) scheduleReconnect()
    }
    ws.onerror = () => ws.close()
  } catch {
    useWsStore.getState().setStatus('closed')
    scheduleReconnect()
  }
}

function scheduleReconnect(): void {
  if (reconnectTimer || closedByUs) return
  const delay = Math.min(500 * 2 ** reconnectAttempt, 15000)
  reconnectAttempt += 1
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    void connectWs()
  }, delay)
}

export function disconnectWs(): void {
  closedByUs = true
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  socket?.close()
  socket = null
  useWsStore.getState().setStatus('closed')
}

/** Client→server — только typing (§9). */
export function sendTyping(chatId: string): void {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: 'typing', data: { chat_id: chatId } }))
  }
}

// периодическая чистка протухшего typing (раз в секунду, дешёвая)
if (typeof window !== 'undefined') {
  setInterval(() => useWsStore.getState().expireTyping(), 1000)
}
