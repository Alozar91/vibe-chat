const KEY = "vibe.lastChat";

export function updateLastChat(chatId: string) {
  try {
    localStorage.setItem(KEY, chatId);
  } catch {
    return;
  }
}

export function getLastChat(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}
