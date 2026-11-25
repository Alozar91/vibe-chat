/**
 * REST-эндпоинты §12 концепции (Docs/android.md §3.8: используются как есть).
 * api() уже делает 401 → refresh → retry; здесь только типизация путей.
 */

import { apiClient } from "../services/api-client";
import type {
  Chat,
  ChatDetail,
  FileOut,
  Message,
  ReactionGroup,
  User,
} from "./types";

export interface ChatListParams {
  /** keyset-пагинация списка чатов не нужна в MVP (десятки чатов); full list */
}

export const chatsApi = {
  list: () => apiClient.get<Chat[]>("/chats"),
  get: (chatId: string) => apiClient.get<ChatDetail>(`/chats/${chatId}`),
  markRead: (chatId: string, messageId: string) =>
    apiClient.post<void>(`/chats/${chatId}/read`, { message_id: messageId }),
};

export interface MessageListParams {
  before?: string;
  after?: string;
  around?: string;
  updated_after?: string;
  limit?: number;
}

export interface SendMessagePayload {
  text?: string;
  attachments?: {
    file_id: string;
    kind: "image" | "video" | "file";
    file_name: string;
    width?: number | null;
    height?: number | null;
    duration_ms?: number | null;
  }[];
  reply_to_id?: string;
  timezone?: string;
}

export const messagesApi = {
  list: (chatId: string, params: MessageListParams = {}) => {
    const q = new URLSearchParams();
    if (params.before) q.set("before", params.before);
    if (params.after) q.set("after", params.after);
    if (params.around) q.set("around", params.around);
    if (params.updated_after) q.set("updated_after", params.updated_after);
    if (params.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return apiClient.get<Message[]>(`/chats/${chatId}/messages${qs ? `?${qs}` : ""}`);
  },
  send: (chatId: string, payload: SendMessagePayload, idempotencyKey: string) =>
    apiClient.post<Message>(`/chats/${chatId}/messages`, payload, {
      "Idempotency-Key": idempotencyKey,
    }),
  edit: (messageId: string, text: string) =>
    apiClient.patch<Message>(`/messages/${messageId}`, { text }),
  delete: (messageId: string) => apiClient.delete<Message>(`/messages/${messageId}`),
  setReaction: (messageId: string, emoji: string) =>
    apiClient.put<ReactionGroup[]>(`/messages/${messageId}/reactions`, { emoji }),
};

export const filesApi = {
  /** Presigned PUT + file_id (pending). sha256 — hex (считает expo-crypto). */
  uploadUrl: (size: number, mime: string, sha256: string) =>
    apiClient.post<{ file_id: string; upload_url: string; expires_in: number }>(
      "/files/upload-url",
      { size, mime, sha256 },
    ),
  complete: (fileId: string) => apiClient.post<FileOut>(`/files/${fileId}/complete`),
  /** Точечные случаи: свежий presigned GET (URL из сообщений TTL-ограничены). */
  url: (fileId: string) =>
    apiClient.get<{ url: string; expires_in: number }>(`/files/${fileId}/url`),
};

export const usersApi = {
  search: (q: string) => apiClient.get<User[]>(`/users?q=${encodeURIComponent(q)}`),
  me: () => apiClient.get<User>("/users/me"),
};
