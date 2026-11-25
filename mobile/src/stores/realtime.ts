/**
 * WS-состояние (§3.3): соединение, typing, presence — Zustand.
 * Аналог frontend/src/realtime/ws.ts; typing протухает через 5 c (§16).
 */

import { create } from "zustand";

export type ConnStatus = "connecting" | "open" | "closed";

interface RealtimeState {
  status: ConnStatus;
  /** chat_id → user_id → ts последнего typing (UI скрывает > 5 c) */
  typing: Record<string, Record<string, number>>;
  /** user_id → presence */
  online: Record<string, { online: boolean; last_seen_at: string | null }>;

  setStatus: (s: ConnStatus) => void;
  setTyping: (chatId: string, userId: string) => void;
  setPresence: (userId: string, online: boolean, lastSeen: string | null) => void;
  /** Чистка протухшего typing (раз в секунду) */
  expireTyping: () => void;
  clear: () => void;
}

export const useRealtime = create<RealtimeState>((set) => ({
  status: "closed",
  typing: {},
  online: {},

  setStatus: (status) => set({ status }),
  setTyping: (chatId, userId) =>
    set((st) => ({
      typing: {
        ...st.typing,
        [chatId]: { ...(st.typing[chatId] ?? {}), [userId]: Date.now() },
      },
    })),
  setPresence: (userId, online, lastSeen) =>
    set((st) => ({
      online: { ...st.online, [userId]: { online, last_seen_at: lastSeen } },
    })),
  expireTyping: () => {
    const cutoff = Date.now() - 5000;
    set((st) => {
      const next: typeof st.typing = {};
      let changed = false;
      for (const [chatId, users] of Object.entries(st.typing)) {
        const alive: Record<string, number> = {};
        for (const [uid, ts] of Object.entries(users)) {
          if (ts > cutoff) alive[uid] = ts;
          else changed = true;
        }
        if (Object.keys(alive).length) next[chatId] = alive;
      }
      return changed ? { typing: next } : {};
    });
  },
  clear: () => set({ typing: {}, online: {}, status: "closed" }),
}));
