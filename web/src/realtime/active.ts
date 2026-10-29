let activeChatId: string | null = null;

export function setActiveChat(chatId: string | null) {
  activeChatId = chatId;
}

export function getActiveChat(): string | null {
  return activeChatId;
}
