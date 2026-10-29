import { api, buildQuery, readCsrfToken, redirectToLogin } from "./client";
import type {
  AdminStats,
  AuditEntry,
  Chat,
  ChatMemberEntry,
  FileReady,
  Invite,
  Message,
  MessagesPage,
  SearchItem,
  SessionEntry,
  UploadIntent,
  User,
} from "./types";

export interface ApiList<T> {
  items: T[];
  next_offset: number | null;
}

export const authApi = {
  sessions: () => api<{ items: SessionEntry[] }>("/v1/auth/sessions"),
  revokeSession: (sessionId: string) =>
    api<null>(`/v1/auth/sessions/${sessionId}`, { method: "DELETE" }),
  logout: () => api<null>("/v1/auth/logout", { method: "POST" }),
  logoutAll: () => api<null>("/v1/auth/logout-all", { method: "POST" }),
  directLogin: (username: string, password: string) =>
    api<User>("/v1/auth/direct-login", { method: "POST", body: { username, password } }),
};

export const meApi = {
  get: () => api<User>("/v1/me"),
  update: (payload: Partial<Pick<User, "full_name" | "phone" | "title">> & { notification_settings?: Record<string, unknown> }) =>
    api<User>("/v1/me", { method: "PATCH", body: payload }),
};

export const usersApi = {
  get: (userId: string) => api<User>(`/v1/users/${userId}`),
  search: (q: string, limit = 20, offset = 0) =>
    api<ApiList<User>>(`/v1/users/search${buildQuery({ q, limit, offset })}`),
};

export interface ChatCreatePayload {
  type: "direct" | "group";
  title?: string;
  description?: string;
  user_id?: string;
  member_ids?: string[];
}

export const chatsApi = {
  list: (limit = 50, offset = 0) => api<ApiList<Chat>>(`/v1/chats${buildQuery({ limit, offset })}`),
  get: (chatId: string) => api<Chat>(`/v1/chats/${chatId}`),
  create: (payload: ChatCreatePayload) => api<Chat>("/v1/chats", { method: "POST", body: payload }),
  update: (chatId: string, payload: { title?: string; description?: string; settings?: Record<string, unknown> }) =>
    api<Chat>(`/v1/chats/${chatId}`, { method: "PATCH", body: payload }),
  remove: (chatId: string) => api<null>(`/v1/chats/${chatId}`, { method: "DELETE" }),
  members: (chatId: string, limit = 50, offset = 0) =>
    api<ApiList<ChatMemberEntry>>(`/v1/chats/${chatId}/members${buildQuery({ limit, offset })}`),
  addMembers: (chatId: string, userIds: string[]) =>
    api<{ added: string[]; skipped: string[] }>(`/v1/chats/${chatId}/members`, {
      method: "POST",
      body: { user_ids: userIds },
    }),
  removeMember: (chatId: string, userId: string) =>
    api<null>(`/v1/chats/${chatId}/members/${userId}`, { method: "DELETE" }),
  leave: (chatId: string) => api<null>(`/v1/chats/${chatId}/leave`, { method: "POST" }),
  read: (chatId: string, lastReadSeq: number) =>
    api<{ unread: number }>(`/v1/chats/${chatId}/read`, {
      method: "POST",
      body: { last_read_seq: lastReadSeq },
    }),
  updateMyMembership: (chatId: string, payload: { notifications?: string; muted_until?: string | null }) =>
    api<{ chat_id: string; notifications: string; muted_until: string | null }>(
      `/v1/chats/${chatId}/members/me`,
      { method: "PATCH", body: payload },
    ),
  invites: (chatId: string) => api<{ items: Invite[] }>(`/v1/chats/${chatId}/invites`),
  createInvite: (chatId: string, payload: { expires_at?: string | null; max_uses?: number | null }) =>
    api<Invite>(`/v1/chats/${chatId}/invites`, { method: "POST", body: payload }),
  revokeInvite: (chatId: string, inviteId: string) =>
    api<null>(`/v1/chats/${chatId}/invites/${inviteId}`, { method: "DELETE" }),
  join: (code: string) => api<Chat>(`/v1/invites/join/${code}`, { method: "POST" }),
};

export interface MessageSendPayload {
  body?: string;
  attachments?: string[];
  reply_to_seq?: number | null;
  forward?: { chat_id: string; seq: number }[];
}

export const messagesApi = {
  list: (chatId: string, params: { limit?: number; before_seq?: number; after_seq?: number } = {}) =>
    api<MessagesPage>(`/v1/chats/${chatId}/messages${buildQuery({ limit: 50, ...params })}`),
  send: (chatId: string, payload: MessageSendPayload, idempotencyKey: string) =>
    api<Message>(`/v1/chats/${chatId}/messages`, {
      method: "POST",
      body: payload,
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  edit: (chatId: string, seq: number, body: string) =>
    api<Message>(`/v1/chats/${chatId}/messages/${seq}`, { method: "PATCH", body: { body } }),
  remove: (chatId: string, seq: number) =>
    api<null>(`/v1/chats/${chatId}/messages/${seq}`, { method: "DELETE" }),
};

export const mediaApi = {
  uploadIntent: (name: string, mimeType: string, sizeBytes: number) =>
    api<UploadIntent>("/v1/media/upload-intents", {
      method: "POST",
      body: { name, mime_type: mimeType, size_bytes: sizeBytes },
    }),
  uploadComplete: (fileId: string) =>
    api<FileReady>("/v1/media/upload-complete", { method: "POST", body: { file_id: fileId } }),
  downloadUrl: (fileId: string) => api<{ url: string; expires_in?: number }>(`/v1/media/${fileId}/url`),
};

export const devicesApi = {
  register: (payload: {
    platform: string;
    push_token?: string;
    webpush_subscription?: Record<string, unknown>;
  }) => api<{ id: string }>("/v1/devices", { method: "POST", body: payload }),
  remove: (deviceId: string) => api<null>(`/v1/devices/${deviceId}`, { method: "DELETE" }),
};

export interface SearchParams {
  q: string;
  type: "messages" | "chats" | "users";
  chat_id?: string;
  author_id?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export const searchApi = {
  search: (params: SearchParams) => api<{ items: SearchItem[]; next_offset: number | null }>(`/v1/search${buildQuery({ limit: 20, ...params })}`),
};

export const adminApi = {
  users: (params: { limit?: number; offset?: number; q?: string }) =>
    api<ApiList<User>>(`/v1/admin/users${buildQuery({ limit: 50, ...params })}`),
  createUser: (payload: { username: string; full_name: string; email?: string; send_email: boolean }) =>
    api<User & { temporary_password?: string }>("/v1/admin/users", { method: "POST", body: payload }),
  importCsv: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch("/v1/admin/users/import", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": readCsrfHeader() },
      body: form,
    }).then(handleResponse<{ created: number; failed: { row: number; error: string }[] }>);
  },
  resetPassword: (userId: string, sendEmail: boolean) =>
    api<{ temporary_password?: string; email_sent?: boolean }>(
      `/v1/admin/users/${userId}/reset-password`,
      { method: "POST", body: { send_email: sendEmail } },
    ),
  disableUser: (userId: string) =>
    api<User>(`/v1/admin/users/${userId}/disable`, { method: "POST", body: {} }),
  enableUser: (userId: string) =>
    api<User>(`/v1/admin/users/${userId}/enable`, { method: "POST", body: {} }),
  userSessions: (userId: string) =>
    api<{ items: SessionEntry[] }>(`/v1/admin/sessions${buildQuery({ user_id: userId })}`),
  revokeSession: (sessionId: string) =>
    api<null>(`/v1/admin/sessions/${sessionId}`, { method: "DELETE" }),
  stats: () => api<AdminStats>("/v1/admin/stats"),
  audit: (params: { limit?: number; offset?: number }) =>
    api<ApiAuditPage>(`/v1/admin/audit${buildQuery({ limit: 50, ...params })}`),
  bots: () =>
    api<{ items: { user_id: string; username: string; full_name: string; description: string | null; is_enabled: boolean; created_at: string }[] }>(
      "/v1/admin/bots",
    ),
  disableBot: (botId: string) =>
    api<{ user_id: string; is_enabled: boolean }>(`/v1/admin/bots/${botId}/disable`, {
      method: "POST",
      body: {},
    }),
};

export interface ApiAuditPage {
  items: AuditEntry[];
  next_offset: number | null;
}

function readCsrfHeader(): string {
  return readCsrfToken();
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (response.status === 401) {
    redirectToLogin();
    throw new Error("unauthorized");
  }
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const err = payload?.error as { message?: string } | undefined;
    throw new Error(err?.message || `Ошибка ${response.status}`);
  }
  return payload as T;
}
