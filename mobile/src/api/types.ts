/**
 * Типы API — копия схем бэкенда (Docs/android.md §5: дублируется с frontend;
 * при расхождении — общий пакет packages/api-types).
 * Источник: backend/app/schemas/{user,chat,message}.py (§12 концепции).
 */

// --- Users (§5) ---

export interface User {
  id: string;
  username: string;
  display_name: string;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  avatar_file_id: string | null;
  is_bot: boolean;
  is_platform_admin: boolean;
  time_display: "browser" | "as_sent" | "fixed" | "utc";
  timezone: string | null;
  last_seen_at: string | null;
}

export type TimeDisplay = User["time_display"];

// --- Chats (§6) ---

export type ChatType = "direct" | "group";
export type MemberRole = "owner" | "admin" | "member";

export interface Chat {
  id: string;
  type: ChatType;
  title: string | null;
  /** created_at последнего сообщения (сортировка списка, §12) */
  last_message_at: string | null;
  unread_count: number;
  avatar_file_id: string | null;
  created_by: string;
  created_at: string;
  deleted_at: string | null;
}

export interface ChatMember {
  user_id: string;
  role: MemberRole;
  last_read_message_id: string | null;
  user: User;
}

export interface ChatDetail extends Chat {
  members: ChatMember[];
}

// --- Messages (§6) ---

export type AttachmentKind = "image" | "video" | "file";

export interface Attachment {
  id: string;
  file_id: string;
  kind: AttachmentKind;
  file_name: string;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  /** presigned GET URL (§8); подпись TTL — не хранить надолго */
  url: string;
  thumb_url: string | null;
}

export interface ReactionGroup {
  emoji: string;
  user_ids: string[];
}

export interface Message {
  id: string;
  chat_id: string;
  sender_id: string | null;
  type: "text" | "system";
  text: string | null;
  payload: Record<string, unknown> | null;
  client_ref: string | null;
  reply_to_id: string | null;
  forward_from_message_id: string | null;
  forward_from_chat_id: string | null;
  forward_snapshot: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  timezone: string | null;
  edited_at: string | null;
  deleted_at: string | null;
  attachments: Attachment[];
  reactions: ReactionGroup[];
}

/** Локальные статусы отправки (§3.10): sending → sent | error */
export type SendStatus = "sending" | "sent" | "error";

/** Сообщение с локальным статусом отправки (пессимистичный рендер) */
export interface LocalMessage extends Message {
  /** undefined для серверных сообщений */
  status?: SendStatus;
}

// --- Files (§8) ---

export interface FileOut {
  id: string;
  status: "pending" | "ready";
  size_bytes: number;
  mime_type: string;
  real_mime_type: string | null;
  thumb_key: string | null;
  blurhash: string | null;
  sha256: string;
  created_at: string;
}

// --- WS-события (§9): конверт {type, data, event_id, ts} ---

export interface WsEnvelope<T = unknown> {
  type: string;
  data: T;
  event_id: string;
  ts: number;
}

export interface MessageEventData {
  /** полный MessageOut-словарь (клиент мержит по id без догоняющего REST) */
  [key: string]: unknown;
}

export interface TypingEventData {
  chat_id: string;
  user_id: string;
}

export interface PresenceEventData {
  user_id: string;
  online: boolean;
  last_seen_at: string | null;
}

export interface ReactionEventData {
  message_id: string;
  chat_id: string;
  reactions: ReactionGroup[];
}

export interface ChatEventData {
  [key: string]: unknown;
}
