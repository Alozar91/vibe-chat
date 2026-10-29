import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import type { InfiniteData } from "@tanstack/react-query";
import { messagesApi } from "../../api/endpoints";
import type { Attachment, Message, MessagesPage, MessageType } from "../../api/types";
import { updateSeqSnapshot } from "../../realtime/snapshot";
import { touchChatLastMessage } from "../chats/queries";

export const messagesKey = (chatId: string) => ["messages", chatId] as const;

const MESSAGE_CACHE_LIMIT = 1000;

export function useMessages(chatId: string | undefined) {
  return useInfiniteQuery({
    queryKey: messagesKey(chatId as string),
    queryFn: ({ pageParam }) =>
      messagesApi.list(chatId as string, pageParam ? { before_seq: pageParam } : {}),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.has_more ? last.next_before_seq : undefined),
    enabled: !!chatId,
    staleTime: 60_000,
    gcTime: 5 * 60_000,
  });
}

export function flattenMessages(data: InfiniteData<MessagesPage> | undefined): Message[] {
  if (!data) return [];
  const chronological = [...data.pages].reverse();
  return chronological.flatMap((page) => page.items);
}

export function maxSeqOfCache(
  qc: ReturnType<typeof useQueryClient>,
  chatId: string,
): number | null {
  const data = qc.getQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId));
  if (!data || !data.pages.length) return null;
  const lastPage = data.pages[data.pages.length - 1];
  let max: number | null = null;
  for (const message of lastPage.items) {
    if (message.seq > 0 && (max === null || message.seq > max)) max = message.seq;
  }
  return max;
}

const fetchingMissing = new Set<string>();

export async function fetchMissing(
  qc: ReturnType<typeof useQueryClient>,
  chatId: string,
  fromSeq: number,
) {
  if (fetchingMissing.has(chatId)) return;
  fetchingMissing.add(chatId);
  try {
    let cursor = fromSeq;
    for (let i = 0; i < 10; i++) {
      const page = await messagesApi.list(chatId, { after_seq: cursor, limit: 100 });
      if (!page.items.length) break;
      appendMessagesBatch(qc, chatId, page.items, false);
      cursor = page.items[page.items.length - 1].seq;
      if (page.items.length < 100) break;
    }
  } catch {
    return;
  } finally {
    fetchingMissing.delete(chatId);
  }
}

export function appendMessages(
  qc: ReturnType<typeof useQueryClient>,
  chatId: string,
  incoming: Message[],
) {
  appendMessagesBatch(qc, chatId, incoming, true);
}

function appendMessagesBatch(
  qc: ReturnType<typeof useQueryClient>,
  chatId: string,
  incoming: Message[],
  checkGap: boolean,
) {
  if (!incoming.length) return;
  const data = qc.getQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId));
  const lastKnown = maxSeqOfCache(qc, chatId);
  for (const message of incoming) {
    if (message.seq > 0) updateSeqSnapshot(chatId, message.seq);
  }
  if (!data) return;

  const existing = new Set<number>();
  const clientKeys = new Set<string>();
  for (const page of data.pages) {
    for (const item of page.items) {
      if (item.seq > 0) existing.add(item.seq);
      if (item._client) clientKeys.add(item._client.key);
    }
  }

  const fresh = incoming.filter((message) => {
    if (message.seq > 0 && existing.has(message.seq)) return false;
    if (message._client && clientKeys.has(message._client.key)) return false;
    return true;
  });
  if (!fresh.length) return;

  if (checkGap && lastKnown !== null) {
    const highest = Math.max(...fresh.filter((m) => m.seq > 0).map((m) => m.seq), 0);
    if (highest > lastKnown + 1) {
      void fetchMissing(qc, chatId, lastKnown);
    }
  }

  const pages = [...data.pages];
  const lastPage = { ...pages[pages.length - 1], items: [...pages[pages.length - 1].items] };
  for (const message of fresh) {
    if (message.seq < 0) {
      lastPage.items.push(message);
      continue;
    }
    let insertAt = 0;
    for (let i = lastPage.items.length - 1; i >= 0; i--) {
      const item = lastPage.items[i];
      if (item.seq > 0 && item.seq < message.seq) {
        insertAt = i + 1;
        break;
      }
      if (i === 0) insertAt = 0;
    }
    lastPage.items.splice(insertAt, 0, message);
  }
  if (lastPage.items.length > MESSAGE_CACHE_LIMIT) {
    lastPage.items = lastPage.items.slice(-MESSAGE_CACHE_LIMIT);
  }
  pages[pages.length - 1] = lastPage;
  qc.setQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId), { ...data, pages });

  const realMessages = fresh.filter((m) => m.seq > 0);
  if (realMessages.length) {
    const newest = realMessages.reduce((a, b) => (b.seq > a.seq ? b : a));
    touchChatLastMessage(qc, chatId, newest.seq, newest.created_at);
  }
}

export function replaceTempMessage(
  qc: ReturnType<typeof useQueryClient>,
  chatId: string,
  clientKey: string,
  serverMessage: Message,
) {
  const data = qc.getQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId));
  if (!data) return;
  const serverSeq = serverMessage.seq;
  const pages = data.pages.map((page, pageIndex) => {
    if (pageIndex !== data.pages.length - 1) return page;
    const items = [...page.items];
    const tempIndex = items.findIndex((item) => item._client?.key === clientKey);
    const realIndex = items.findIndex((item) => item.seq === serverSeq);
    if (tempIndex >= 0) {
      if (realIndex >= 0) items.splice(tempIndex, 1);
      else items[tempIndex] = serverMessage;
    }
    return { ...page, items };
  });
  qc.setQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId), { ...data, pages });
}

export function setTempStatus(
  qc: ReturnType<typeof useQueryClient>,
  chatId: string,
  clientKey: string,
  status: "sending" | "failed",
  error?: string,
) {
  const data = qc.getQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId));
  if (!data) return;
  const pages = data.pages.map((page, pageIndex) => {
    if (pageIndex !== data.pages.length - 1) return page;
    const items = page.items.map((item) =>
      item._client?.key === clientKey
        ? { ...item, _client: { key: clientKey, status, error } }
        : item,
    );
    return { ...page, items };
  });
  qc.setQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId), { ...data, pages });
}

export function removeTempMessage(
  qc: ReturnType<typeof useQueryClient>,
  chatId: string,
  clientKey: string,
) {
  const data = qc.getQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId));
  if (!data) return;
  const pages = data.pages.map((page, pageIndex) => {
    if (pageIndex !== data.pages.length - 1) return page;
    return {
      ...page,
      items: page.items.filter((item) => item._client?.key !== clientKey),
    };
  });
  qc.setQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId), { ...data, pages });
}

export function markMessageUpdated(
  qc: ReturnType<typeof useQueryClient>,
  chatId: string,
  updated: Message,
) {
  const data = qc.getQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId));
  if (!data) return;
  const pages = data.pages.map((page) => ({
    ...page,
    items: page.items.map((item) =>
      item.seq === updated.seq ? { ...item, ...updated } : item,
    ),
  }));
  qc.setQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId), { ...data, pages });
}

export function markMessageDeleted(
  qc: ReturnType<typeof useQueryClient>,
  chatId: string,
  seq: number,
) {
  const data = qc.getQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId));
  if (!data) return;
  const pages = data.pages.map((page) => ({
    ...page,
    items: page.items.map((item) =>
      item.seq === seq
        ? { ...item, body: "", attachments: [], mentions: [], mentions_all: false, deleted_at: new Date().toISOString() }
        : item,
    ),
  }));
  qc.setQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId), { ...data, pages });
}

export function useEditMessage(chatId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ seq, body }: { seq: number; body: string }) =>
      messagesApi.edit(chatId, seq, body),
    onSuccess: (message) => {
      markMessageUpdated(qc, chatId, message);
    },
  });
}

export function useDeleteMessage(chatId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (seq: number) => messagesApi.remove(chatId, seq),
    onSuccess: (_data, seq) => {
      markMessageDeleted(qc, chatId, seq);
    },
  });
}

let tempSeqCounter = -1;

export function createTempMessage(
  chatId: string,
  senderId: string,
  clientKey: string,
  payload: { body?: string; reply_to_seq?: number | null; forward?: { chat_id: string; seq: number }[] },
  attachments: Attachment[],
): Message {
  const type: MessageType = attachments.length
    ? attachments.every((a) => a.mime_type.startsWith("image/"))
      ? "image"
      : attachments.every((a) => a.mime_type.startsWith("video/"))
        ? "video"
        : attachments.every((a) => a.mime_type.startsWith("audio/"))
          ? "audio"
          : "file"
    : "text";
  return {
    chat_id: chatId,
    seq: tempSeqCounter--,
    sender_id: senderId,
    type,
    body: payload.body || "",
    data: payload.forward
      ? ({ forwarded_from: payload.forward.map((f) => ({ chat_id: f.chat_id, seq: f.seq, sender_id: "" })) } as Message["data"])
      : {},
    reply_to_seq: payload.reply_to_seq ?? null,
    mentions: [],
    mentions_all: false,
    attachments,
    reactions: {},
    edited_at: null,
    deleted_at: null,
    created_at: new Date().toISOString(),
    _client: { key: clientKey, status: "sending" },
  };
}
