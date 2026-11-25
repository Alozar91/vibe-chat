/**
 * Диспетчер realtime-событий (§3.3): одна точка входа от ws-client.
 * message.* → идемпотентный upsert в кэш ленты; chat.* → инвалидация;
 * typing/presence → Zustand. Реконнект → догоняние через updated_after (§9).
 */

import type { QueryClient } from "@tanstack/react-query";
import { messagesApi } from "../api/endpoints";
import { queryKeys } from "../api/query-keys";
import type { Chat, LocalMessage, Message, WsEnvelope } from "../api/types";
import { upsertMessageInCache } from "../hooks/use-send-message";
import { useRealtime } from "../stores/realtime";
import { wsClient } from "./ws-client";

/** Сообщение из WS message.* — сервер оборачивает payload: {message: <MessageOut>} (§9). */
function asMessage(data: unknown): Message | null {
  if (typeof data !== "object" || data === null) return null;
  const unwrapped = (data as Record<string, unknown>).message ?? data;
  if (typeof unwrapped !== "object" || unwrapped === null) return null;
  const d = unwrapped as Record<string, unknown>;
  if (typeof d.id !== "string" || typeof d.chat_id !== "string") return null;
  return unwrapped as unknown as Message;
}

/** Все ленты в кэше (для догоняния). */
export async function catchUpOnReconnect(queryClient: QueryClient): Promise<void> {
  const feeds = queryClient
    .getQueryCache()
    .findAll({ predicate: (q) => Array.isArray(q.queryKey) && q.queryKey[0] === "messages" && q.queryKey[1] === "feed" });
  await Promise.allSettled(
    feeds.map(async (query) => {
      const chatId = String(query.queryKey[2]);
      const data = queryClient.getQueryData<{
        pages: { messages: (Message | LocalMessage)[] }[];
        pageParams: unknown[];
      }>(query.queryKey);
      if (!data) return;
      // максимум updated_at по кэшу — курсор догоняния (§6)
      let maxUpdated: string | null = null;
      for (const page of data.pages) {
        for (const m of page.messages) {
          if (!maxUpdated || m.updated_at > maxUpdated) maxUpdated = m.updated_at;
        }
      }
      if (!maxUpdated) return;
      const delta = await messagesApi.list(chatId, { updated_after: maxUpdated, limit: 100 });
      for (const m of delta) {
        upsertMessageInCache(queryClient, { ...m, status: "sent" } as LocalMessage);
      }
    }),
  );
}

export function installRealtimeSync(queryClient: QueryClient): () => void {
  let lastStatus: "open" | "closed" = "closed";
  wsClient.onConnectionChange((connected) => {
    const status = connected ? "open" : "closed";
    useRealtime.getState().setStatus(status);
    // поднятие соединения после разрыва → догоняние (§3.3)
    if (connected && lastStatus === "closed") {
      void catchUpOnReconnect(queryClient);
    }
    lastStatus = status;
  });

  const dispatch = (envelope: WsEnvelope) => {
    const data = envelope.data;
    switch (envelope.type) {
      case "message.new": {
        const m = asMessage(data);
        if (!m) return;
        upsertMessageInCache(queryClient, { ...m, status: "sent" } as LocalMessage);
        // last_message_at/unread_count списка — refetch (дёшево, десятки чатов)
        void queryClient.invalidateQueries({ queryKey: queryKeys.chats.list() });
        return;
      }
      case "message.edited":
      case "message.deleted": {
        const m = asMessage(data);
        if (!m) return;
        upsertMessageInCache(queryClient, { ...m, status: "sent" } as LocalMessage);
        return;
      }
      case "reaction.updated": {
        const d = data as { message_id?: string; chat_id?: string; reactions?: Message["reactions"] };
        if (!d?.message_id || !d?.chat_id || !d?.reactions) return;
        // точечное обновление реакций в кэше ленты
        const feedKey = queryKeys.messages.feed(d.chat_id);
        queryClient.setQueryData<{
          pages: { messages: Message[] }[];
          pageParams: unknown[];
        }>(feedKey, (old) => {
          if (!old) return old;
          const pages = old.pages.map((page) => ({
            ...page,
            messages: page.messages.map((m) =>
              m.id === d.message_id ? { ...m, reactions: d.reactions! } : m,
            ),
          }));
          return { ...old, pages };
        });
        return;
      }
      case "chat.created":
      case "chat.updated": {
        const d = data as { id?: string; deleted?: boolean };
        if (d?.deleted === true && d.id) {
          // soft delete чата: убрать из списка (§6) и сбросить кэш
          queryClient.setQueryData<Chat[]>(queryKeys.chats.list(), (old) =>
            (old ?? []).filter((c) => c.id !== d.id),
          );
          void queryClient.removeQueries({ queryKey: queryKeys.chats.detail(d.id) });
          void queryClient.removeQueries({ queryKey: queryKeys.messages.feed(d.id) });
          return;
        }
        void queryClient.invalidateQueries({ queryKey: queryKeys.chats.all() });
        return;
      }
      case "member.joined":
      case "member.left": {
        const d = data as { chat_id?: string };
        if (d?.chat_id) {
          void queryClient.invalidateQueries({ queryKey: queryKeys.chats.detail(d.chat_id) });
        }
        return;
      }
      case "typing": {
        const d = data as { chat_id?: string; user_id?: string };
        if (d?.chat_id && d?.user_id) useRealtime.getState().setTyping(d.chat_id, d.user_id);
        return;
      }
      case "presence": {
        const d = data as { user_id?: string; online?: boolean; last_seen_at?: string | null };
        if (d?.user_id) {
          useRealtime.getState().setPresence(d.user_id, Boolean(d.online), d.last_seen_at ?? null);
        }
        return;
      }
      case "read": {
        // чужие курсоры прочтения влияют только на «прочитано»-отметки в UI;
        // unread_count свой — приходит через invalidate после send/markRead
        return;
      }
      default:
        return; // call.* и прочие — этапы звонков, игнор
    }
  };

  wsClient.onDispatch(dispatch);
  return () => wsClient.onDispatch(null);
}
