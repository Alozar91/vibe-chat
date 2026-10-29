import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { chatsApi, type ChatCreatePayload } from "../../api/endpoints";
import type { Chat, ChatMemberEntry } from "../../api/types";
import { ws } from "../../realtime/ws";
import { updateSeqSnapshot } from "../../realtime/snapshot";
import { useToastStore } from "../../stores/ui";
import type { InfiniteData } from "@tanstack/react-query";

export const chatsKey = ["chats"] as const;

export function useChats() {
  return useInfiniteQuery({
    queryKey: chatsKey,
    queryFn: ({ pageParam }) => chatsApi.list(50, pageParam as number),
    initialPageParam: 0,
    getNextPageParam: (last) => last.next_offset ?? undefined,
    staleTime: 10_000,
  });
}

export function useChat(chatId: string | undefined) {
  return useQuery({
    queryKey: ["chat", chatId],
    queryFn: () => chatsApi.get(chatId as string),
    enabled: !!chatId,
    staleTime: 30_000,
  });
}

export function useChatMembers(chatId: string | undefined) {
  return useInfiniteQuery({
    queryKey: ["chat", chatId, "members"],
    queryFn: ({ pageParam }) => chatsApi.members(chatId as string, 50, pageParam as number),
    initialPageParam: 0,
    getNextPageParam: (last) => last.next_offset ?? undefined,
    enabled: !!chatId,
    staleTime: 30_000,
  });
}

export function flattenMembers(data: InfiniteData<{ items: ChatMemberEntry[] }> | undefined): ChatMemberEntry[] {
  if (!data) return [];
  return data.pages.flatMap((page) => page.items);
}

export function chatsFromCache(qc: ReturnType<typeof useQueryClient>): Chat[] {
  const data = qc.getQueryData<InfiniteData<{ items: Chat[] }>>(chatsKey);
  if (!data) return [];
  return data.pages.flatMap((page) => page.items);
}

export function updateChatInCaches(qc: ReturnType<typeof useQueryClient>, chat: Chat) {
  qc.setQueryData<InfiniteData<{ items: Chat[] }>>(chatsKey, (prev) => {
    if (!prev) return prev;
    let replaced = false;
    const pages = prev.pages.map((page) => ({
      ...page,
      items: page.items.map((item) => {
        if (item.id === chat.id) {
          replaced = true;
          return { ...item, ...chat };
        }
        return item;
      }),
    }));
    if (!replaced && pages.length) {
      pages[0] = { ...pages[0], items: [chat, ...pages[0].items] };
    }
    return { ...prev, pages };
  });
  qc.setQueryData<Chat>(["chat", chat.id], chat);
}

export function touchChatLastMessage(
  qc: ReturnType<typeof useQueryClient>,
  chatId: string,
  seq: number,
  at: string,
) {
  const patch = (chat: Chat): Chat => ({
    ...chat,
    last_message_seq: Math.max(chat.last_message_seq, seq),
    last_message_at: at,
  });
  qc.setQueryData<InfiniteData<{ items: Chat[] }>>(chatsKey, (prev) => {
    if (!prev) return prev;
    const pages = prev.pages.map((page) => ({
      ...page,
      items: page.items.map((item) => (item.id === chatId ? patch(item) : item)),
    }));
    return { ...prev, pages };
  });
  qc.setQueryData<Chat>(["chat", chatId], (prev) => (prev ? patch(prev) : prev));
}

export function bumpUnread(qc: ReturnType<typeof useQueryClient>, chatId: string) {
  const patch = (chat: Chat): Chat => ({ ...chat, unread: chat.unread + 1 });
  qc.setQueryData<InfiniteData<{ items: Chat[] }>>(chatsKey, (prev) => {
    if (!prev) return prev;
    const pages = prev.pages.map((page) => ({
      ...page,
      items: page.items.map((item) => (item.id === chatId ? patch(item) : item)),
    }));
    return { ...prev, pages };
  });
  qc.setQueryData<Chat>(["chat", chatId], (prev) => (prev ? patch(prev) : prev));
}

export function setChatUnread(qc: ReturnType<typeof useQueryClient>, chatId: string, unread: number) {
  const patch = (chat: Chat): Chat => ({ ...chat, unread });
  qc.setQueryData<InfiniteData<{ items: Chat[] }>>(chatsKey, (prev) => {
    if (!prev) return prev;
    const pages = prev.pages.map((page) => ({
      ...page,
      items: page.items.map((item) => (item.id === chatId ? patch(item) : item)),
    }));
    return { ...prev, pages };
  });
  qc.setQueryData<Chat>(["chat", chatId], (prev) => (prev ? patch(prev) : prev));
}

export function removeChatFromCaches(qc: ReturnType<typeof useQueryClient>, chatId: string) {
  qc.setQueryData<InfiniteData<{ items: Chat[] }>>(chatsKey, (prev) => {
    if (!prev) return prev;
    const pages = prev.pages.map((page) => ({
      ...page,
      items: page.items.filter((item) => item.id !== chatId),
    }));
    return { ...prev, pages };
  });
  qc.removeQueries({ queryKey: ["chat", chatId] });
}

export function useCreateChat(onCreated: (chat: Chat) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ChatCreatePayload) => chatsApi.create(payload),
    onSuccess: (chat) => {
      ws.sendSubscribeRefresh();
      updateChatInCaches(qc, chat);
      onCreated(chat);
    },
  });
}

export function useJoinChat(onJoined: (chat: Chat) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => chatsApi.join(code),
    onSuccess: (chat) => {
      ws.sendSubscribeRefresh();
      updateChatInCaches(qc, chat);
      onJoined(chat);
    },
  });
}

export async function markRead(qc: ReturnType<typeof useQueryClient>, chatId: string, lastSeq: number) {
  if (lastSeq <= 0) return;
  setChatUnread(qc, chatId, 0);
  updateSeqSnapshot(chatId, lastSeq);
  try {
    await chatsApi.read(chatId, lastSeq);
  } catch {
    return;
  }
}

export function useLeaveChat() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (chatId: string) => chatsApi.leave(chatId),
    onSuccess: (_data, chatId) => {
      removeChatFromCaches(qc, chatId);
      useToastStore.getState().push({ kind: "success", title: "Вы покинули чат" });
      ws.sendSubscribeRefresh();
    },
  });
}

export function useDeleteChat() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (chatId: string) => chatsApi.remove(chatId),
    onSuccess: (_data, chatId) => {
      removeChatFromCaches(qc, chatId);
      ws.sendSubscribeRefresh();
    },
  });
}
