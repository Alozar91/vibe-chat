import { create } from "zustand";
import { randomId } from "../lib/format";

export type WsStatus = "connecting" | "online" | "offline";

export interface LightboxState {
  items: { url: string; name: string }[];
  index: number;
}

interface UiState {
  wsStatus: WsStatus;
  setWsStatus: (status: WsStatus) => void;
  typing: Record<string, Record<string, number>>;
  setTyping: (chatId: string, userId: string) => void;
  clearTyping: (chatId: string, userId: string) => void;
  pruneTyping: () => void;
  presence: Record<string, { online: boolean; at: number }>;
  setPresence: (userId: string, online: boolean) => void;
  lightbox: LightboxState | null;
  openLightbox: (items: { url: string; name: string }[], index: number) => void;
  closeLightbox: () => void;
  lightboxStep: (delta: number) => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  wsStatus: "connecting",
  setWsStatus: (status) => set({ wsStatus: status }),
  typing: {},
  setTyping: (chatId, userId) =>
    set((state) => ({
      typing: {
        ...state.typing,
        [chatId]: { ...(state.typing[chatId] || {}), [userId]: Date.now() + 5000 },
      },
    })),
  clearTyping: (chatId, userId) =>
    set((state) => {
      const chat = { ...(state.typing[chatId] || {}) };
      delete chat[userId];
      return { typing: { ...state.typing, [chatId]: chat } };
    }),
  pruneTyping: () => {
    const now = Date.now();
    let changed = false;
    const next: Record<string, Record<string, number>> = {};
    for (const [chatId, users] of Object.entries(get().typing)) {
      const kept: Record<string, number> = {};
      for (const [userId, expiry] of Object.entries(users)) {
        if (expiry > now) kept[userId] = expiry;
        else changed = true;
      }
      if (Object.keys(kept).length) next[chatId] = kept;
    }
    if (changed) set({ typing: next });
  },
  presence: {},
  setPresence: (userId, online) =>
    set((state) => ({
      presence: {
        ...state.presence,
        [userId]: { online, at: Date.now() },
      },
    })),
  lightbox: null,
  openLightbox: (items, index) => set({ lightbox: { items, index } }),
  closeLightbox: () => set({ lightbox: null }),
  lightboxStep: (delta) => {
    const lb = get().lightbox;
    if (!lb) return;
    const next = (lb.index + delta + lb.items.length) % lb.items.length;
    set({ lightbox: { items: lb.items, index: next } });
  },
}));

export interface Toast {
  id: string;
  kind: "info" | "error" | "success";
  title: string;
  body?: string;
  onClick?: () => void;
}

interface ToastState {
  toasts: Toast[];
  push: (toast: Omit<Toast, "id">) => void;
  dismiss: (id: string) => void;
}

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (toast) => {
    const id = randomId();
    set((state) => ({ toasts: [...state.toasts.slice(-4), { ...toast, id }] }));
    window.setTimeout(() => {
      set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
    }, 5000);
  },
  dismiss: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));

export function toastError(error: unknown, fallback = "Ошибка") {
  const message = error instanceof Error ? error.message : fallback;
  useToastStore.getState().push({ kind: "error", title: fallback, body: message });
}
