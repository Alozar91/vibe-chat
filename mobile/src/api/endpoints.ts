/**
 * REST-эндпоинты §12 концепции (Docs/android.md §3.8: используются как есть).
 * api() уже делает 401 → refresh → retry; здесь только типизация путей.
 */

import { apiClient } from "../services/api-client";
import type {
  Call,
  CallToken,
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
  /** Direct-чат с пользователем: {chat_id, created} — повторный вызов вернёт существующий (§12). */
  createDirect: (userId: string) =>
    apiClient.post<{ chat_id: string; created: boolean }>("/chats/direct", { user_id: userId }),
  /** Групповой: title + участники (creator добавляется сервером, в member_ids не нужен). */
  createGroup: (title: string, memberIds: string[]) =>
    apiClient.post<Chat>("/chats", { title, member_ids: memberIds }),
  /** Переименование группы (owner/admin, §12). */
  rename: (chatId: string, title: string) =>
    apiClient.patch<Chat>(`/chats/${chatId}`, { title }),
  /** Выход из группы: удаление себя = remove_member себя (leave разрешён, §12). */
  leave: (chatId: string, meId: string) =>
    apiClient.delete<void>(`/chats/${chatId}/members/${meId}`),
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
  /** Пересылка (§6): копия в выбранные чаты, вложения копируются на сервере. */
  forward: (messageId: string, chatIds: string[]) =>
    apiClient.post<Message[]>(`/messages/${messageId}/forward`, { chat_ids: chatIds }),
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
  /** Персональные данные — в PostgreSQL системы (§5); username/пароль не меняются здесь. */
  updateMe: (patch: Partial<Pick<User, "display_name" | "first_name" | "last_name" | "email" | "time_display" | "timezone">>) =>
    apiClient.patch<User>("/users/me", patch),
};

export interface Invite {
  id: string;
  max_uses: number | null;
  uses_count: number;
  expires_at: string | null;
  deactivated_at: string | null;
  created_at: string;
}

export const invitesApi = {
  list: () => apiClient.get<Invite[]>("/invites"),
  /** code — в ответе только при создании (§5: хэш в БД, показать один раз). */
  create: (maxUses?: number | null, expiresAt?: string | null) =>
    apiClient.post<Invite & { code: string }>("/invites", {
      max_uses: maxUses ?? undefined,
      expires_at: expiresAt ?? undefined,
    }),
  deactivate: (id: string) => apiClient.post<Invite>(`/invites/${id}/deactivate`),
};

export const callsApi = {
  /** direct → ringing-модель (§17 A); group → сразу active (join-модель §17 B) */
  start: (chatId: string, kind: "audio" | "video" = "audio") =>
    apiClient.post<Call>("/calls", { chat_id: chatId, kind }),
  accept: (callId: string) => apiClient.post<Call>(`/calls/${callId}/accept`),
  reject: (callId: string) => apiClient.post<Call>(`/calls/${callId}/reject`),
  cancel: (callId: string) => apiClient.post<Call>(`/calls/${callId}/cancel`),
  join: (callId: string) => apiClient.post<Call>(`/calls/${callId}/join`),
  leave: (callId: string) => apiClient.post<Call>(`/calls/${callId}/leave`),
  /** room-токен LiveKit (TTL ~10 мин, только участник звонка — §17) */
  token: (callId: string) => apiClient.post<CallToken>(`/calls/${callId}/token`),
};
