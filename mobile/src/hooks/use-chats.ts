/**
 * Хуки TanStack Query: useChats (список), useChatDetail (участники),
 * useMessages (infinite-лента, keyset по UUIDv7 ?before=).
 * staleTime согласован с WS: живые события обновляют кэш напрямую,
 * REST — источник догоняния после реконнекта/холодного старта.
 */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { chatsApi, messagesApi, type MessageListParams } from "../api/endpoints";
import { queryKeys } from "../api/query-keys";
import type { Chat, ChatDetail, Message } from "../api/types";

const CHATS_STALE_MS = 30_000;
const MESSAGES_STALE_MS = 30_000;

/** Список чатов: сортировка по last_message_at делает UI (§3.10). */
export function useChats() {
  return useQuery<Chat[]>({
    queryKey: queryKeys.chats.list(),
    queryFn: () => chatsApi.list(),
    staleTime: CHATS_STALE_MS,
  });
}

/** Детали чата (участники — имена direct-чатов, роли). */
export function useChatDetail(chatId: string) {
  return useQuery<ChatDetail>({
    queryKey: queryKeys.chats.detail(chatId),
    queryFn: () => chatsApi.get(chatId),
    staleTime: CHATS_STALE_MS,
  });
}

export interface MessagesPage {
  messages: Message[];
}

/**
 * Лента чата — infinite, пагинация «вверх» по ?before= (UUIDv7, §3.3).
 * Первая страница: последние 50; «вниз» — только realtime/updated_after (§3.3).
 * Бэкенд возвращает ASC (старые сверху); страница короче limit = начало чата.
 */
export function useMessages(chatId: string, limit = 50) {
  // Ключ — queryKeys.messages.feed(chatId) (с { limit: 50 }); limit хелпера
  // должен совпадать, иначе upsert-обновления (send/WS) не попадут в кэш
  return useInfiniteQuery<MessagesPage>({
    queryKey: [...queryKeys.messages.feed(chatId)],
    queryFn: async ({ pageParam }) => {
      const list = await messagesApi.list(chatId, {
        before: pageParam as string | undefined,
        limit,
      });
      return { messages: list };
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage, allPages) => {
      // следующая страница — старее: cursor = min id последней страницы;
      // неполная первая страница означает, что истории меньше limit и
      // «before»-страниц нет вовсе
      const last = lastPage.messages;
      if (last.length === 0) return undefined;
      if (allPages.length === 1 && last.length < 50) return undefined;
      if (last.length < 50) return undefined;
      return last[0].id;
    },
    staleTime: MESSAGES_STALE_MS,
  });
}

/** Прочтение чата: MAX-курсор (§6); вызывать при открытии/скролле ленты. */
export function useMarkRead(chatId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (messageId: string) => chatsApi.markRead(chatId, messageId),
    onSuccess: () => {
      // unread_count пересчитается; полный refetch списка — десятки чатов, дёшево
      void queryClient.invalidateQueries({ queryKey: queryKeys.chats.list() });
    },
  });
}
