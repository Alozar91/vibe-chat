import type { Message, MessageType } from "../api/types";
import { getActiveChat } from "./active";
import { queryClient } from "../app/query";
import {
  appendMessages,
  fetchMissing,
  markMessageDeleted,
  markMessageUpdated,
  maxSeqOfCache,
} from "../features/messages/queries";
import { bumpUnread, touchChatLastMessage } from "../features/chats/queries";
import { plainPreview } from "../lib/markdown";
import { usePreviewStore } from "../stores/preview";
import { useToastStore, useUiStore } from "../stores/ui";
import { chatsFromCache } from "../features/chats/queries";
import { appNavigate } from "./navigator";

export function handleEvent(type: string, data: Record<string, unknown>) {
  switch (type) {
    case "message.new":
      onMessageNew(data);
      break;
    case "message.updated":
      onMessageUpdated(data);
      break;
    case "message.deleted":
      onMessageDeleted(data);
      break;
    case "chat.created":
    case "chat.updated":
    case "chat.deleted":
      onChatChanged(type);
      break;
    case "chat.member.joined":
    case "chat.member.left":
      onChatMembersChanged(data);
      break;
    case "chat.read":
      onChatRead(data);
      break;
    case "typing.start":
    case "typing.stop":
      onTyping(type, data);
      break;
    case "presence.update":
      onPresence(data);
      break;
    default:
      break;
  }
}

function normalizeIncoming(data: Record<string, unknown>): Message | null {
  const chatId = data.chat_id ? String(data.chat_id) : "";
  const seq = Number(data.seq);
  if (!chatId || !Number.isFinite(seq)) return null;
  const type = (data.type || data.message_type || "text") as MessageType;
  return {
    chat_id: chatId,
    seq,
    sender_id: String(data.sender_id || ""),
    type,
    body: String(data.body || ""),
    data: (data.data as Message["data"]) || {},
    reply_to_seq: (data.reply_to_seq as number | null) ?? null,
    mentions: (data.mentions as Message["mentions"]) || [],
    mentions_all: Boolean(data.mentions_all),
    attachments: (data.attachments as Message["attachments"]) || [],
    reactions: (data.reactions as Message["reactions"]) || {},
    edited_at: (data.edited_at as string | null) ?? null,
    deleted_at: (data.deleted_at as string | null) ?? null,
    created_at: String(data.created_at || new Date().toISOString()),
  };
}

function previewOf(message: Message): string {
  if (message.deleted_at) return "Сообщение удалено";
  if (message.attachments.length && !message.body) {
    return `📎 ${message.attachments.map((a) => a.name).join(", ")}`;
  }
  return plainPreview(message.body);
}

function onMessageNew(data: Record<string, unknown>) {
  const message = normalizeIncoming(data);
  if (!message) return;
  const chatId = message.chat_id;
  const lastKnown = maxSeqOfCache(queryClient, chatId);
  if (lastKnown !== null && message.seq > lastKnown + 1) {
    void fetchMissing(queryClient, chatId, lastKnown);
  }
  appendMessages(queryClient, chatId, [message]);
  touchChatLastMessage(queryClient, chatId, message.seq, message.created_at);
  usePreviewStore.getState().setPreview(chatId, { text: previewOf(message), at: message.created_at });

  const me = queryClient.getQueryData<{ id: string }>(["me"]);
  const isMine = message.sender_id === me?.id;
  const active = getActiveChat() === chatId && document.visibilityState === "visible";
  if (!active && !isMine) {
    bumpUnread(queryClient, chatId);
  }
  if (!isMine) {
    notifyInApp(chatId, message);
  }
}

function onMessageUpdated(data: Record<string, unknown>) {
  const message = normalizeIncoming(data);
  if (!message) return;
  markMessageUpdated(queryClient, message.chat_id, message);
}

function onMessageDeleted(data: Record<string, unknown>) {
  const chatId = data.chat_id ? String(data.chat_id) : "";
  const seq = Number(data.seq);
  if (!chatId || !Number.isFinite(seq)) return;
  markMessageDeleted(queryClient, chatId, seq);
}

function onChatChanged(_type: string) {
  void queryClient.invalidateQueries({ queryKey: ["chats"] });
}

function onChatMembersChanged(data: Record<string, unknown>) {
  const chatId = data.chat_id ? String(data.chat_id) : "";
  if (!chatId) return;
  void queryClient.invalidateQueries({ queryKey: ["chat", chatId, "members"] });
  void queryClient.invalidateQueries({ queryKey: ["chat", chatId] });
  void queryClient.invalidateQueries({ queryKey: ["chats"] });
}

function onChatRead(data: Record<string, unknown>) {
  const chatId = data.chat_id ? String(data.chat_id) : "";
  const userId = data.user_id ? String(data.user_id) : "";
  const lastReadSeq = Number(data.last_read_seq);
  if (!chatId || !userId || !Number.isFinite(lastReadSeq)) return;
  const members = queryClient.getQueryData<{
    pages: { items: { user: { id: string }; last_read_seq: number }[] }[];
  }>(["chat", chatId, "members"]);
  if (!members) return;
  const pages = members.pages.map((page) => ({
    ...page,
    items: page.items.map((entry) =>
      entry.user.id === userId ? { ...entry, last_read_seq: lastReadSeq } : entry,
    ),
  }));
  queryClient.setQueryData(["chat", chatId, "members"], { ...members, pages });
}

function onTyping(type: string, data: Record<string, unknown>) {
  const chatId = data.chat_id ? String(data.chat_id) : "";
  const userId = data.user_id ? String(data.user_id) : "";
  if (!chatId || !userId) return;
  if (type === "typing.start") useUiStore.getState().setTyping(chatId, userId);
  else useUiStore.getState().clearTyping(chatId, userId);
}

function onPresence(data: Record<string, unknown>) {
  const userId = data.user_id ? String(data.user_id) : "";
  if (!userId) return;
  useUiStore.getState().setPresence(userId, Boolean(data.online));
}

function notifyInApp(chatId: string, message: Message) {
  const chat = chatsFromCache(queryClient).find((item) => item.id === chatId);
  if (chat?.muted_until) return;
  const me = queryClient.getQueryData<{ id: string }>(["me"]);
  const mentioned = me ? message.mentions.some((m) => m.user_id === me.id) || message.mentions_all : false;
  const notifications = chat ? getChatNotifications(chat) : "all";
  if (notifications === "none") return;
  if (notifications === "mentions" && !mentioned) return;
  const title = chat
    ? chat.type === "direct"
      ? chat.counterpart?.full_name || "Личный чат"
      : chat.title || "Группа"
    : "Новое сообщение";
  useToastStore.getState().push({
    kind: "info",
    title,
    body: previewOf(message),
    onClick: () => appNavigate(`/chat/${chatId}`),
  });
  playNotificationSound();
}

function getChatNotifications(chat: { settings: Record<string, unknown> }): "all" | "mentions" | "none" {
  const value = chat.settings?.notifications;
  if (value === "mentions" || value === "none" || value === "all") return value;
  return "all";
}

function playNotificationSound() {
  try {
    if (localStorage.getItem("vibe.sound") === "off") return;
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = 660;
    gain.gain.setValueAtTime(0.04, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.25);
    osc.start();
    osc.stop(ctx.currentTime + 0.25);
  } catch {
    return;
  }
}
