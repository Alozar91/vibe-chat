import { create } from "zustand";

export interface ChatPreview {
  text: string;
  at: string;
}

const KEY = "vibe.preview.v1";
const MAX_ITEMS = 300;

interface PreviewState {
  previews: Record<string, ChatPreview>;
  setPreview: (chatId: string, preview: ChatPreview) => void;
}

function hydrate(): Record<string, ChatPreview> {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, ChatPreview>;
    return typeof parsed === "object" && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
}

export const usePreviewStore = create<PreviewState>((set, get) => ({
  previews: hydrate(),
  setPreview: (chatId, preview) => {
    const next = { ...get().previews, [chatId]: preview };
    const ids = Object.keys(next);
    if (ids.length > MAX_ITEMS) {
      for (const id of ids.slice(0, ids.length - MAX_ITEMS)) delete next[id];
    }
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      return;
    }
    set({ previews: next });
  },
}));
