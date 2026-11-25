/**
 * Query keys (иерархия TanStack Query v5) + централизованная инвалидация.
 * Инвалидация — через queryClient.invalidateQueries по иерархии ключей.
 */

export const queryKeys = {
  chats: {
    all: () => ["chats"] as const,
    list: () => [...queryKeys.chats.all(), "list"] as const,
    detail: (chatId: string) => [...queryKeys.chats.all(), "detail", chatId] as const,
  },
  messages: {
    all: () => ["messages"] as const,
    /**
     * Лента чата (infinite); единственный вариант ключа — useMessages и
     * upsert-логика используют один и тот же ключ (иначе setQueryData мимо).
     */
    feed: (chatId: string) => [...queryKeys.messages.all(), "feed", chatId, { limit: 50 }] as const,
  },
  users: {
    all: () => ["users"] as const,
    search: (q: string) => [...queryKeys.users.all(), "search", q] as const,
  },
} as const;
