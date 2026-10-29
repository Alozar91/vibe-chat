export type UserKind = "human" | "bot";
export type OrgRole = "owner" | "admin" | "member";
export type UserStatus = "active" | "disabled";

export interface NotificationSettings {
  default_mode?: "all" | "mentions" | "none";
  dnd_until?: string | null;
  [key: string]: unknown;
}

export interface User {
  id: string;
  kind: UserKind;
  username: string;
  full_name: string;
  avatar_url: string | null;
  title: string | null;
  status: UserStatus;
  email?: string | null;
  phone?: string | null;
  role?: OrgRole;
  source?: string;
  notification_settings?: NotificationSettings;
  created_at?: string;
  last_login_at?: string | null;
  temporary_password?: string;
}

export interface Chat {
  id: string;
  type: "direct" | "group";
  title: string | null;
  description: string | null;
  avatar_url: string | null;
  created_by: string | null;
  members_count: number;
  last_message_seq: number;
  last_message_at: string | null;
  settings: Record<string, unknown>;
  my_role: "owner" | "admin" | "member";
  unread: number;
  muted_until: string | null;
  created_at: string;
  updated_at: string;
  counterpart?: User | null;
}

export interface ChatMemberEntry {
  user: User;
  role: "owner" | "admin" | "member";
  status: string;
  last_read_seq: number;
  joined_at: string;
}

export interface Attachment {
  file_id: string;
  name: string;
  mime_type: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  thumbnail_url: string | null;
  url: string;
}

export interface Mention {
  user_id: string;
  username: string;
}

export interface ForwardedRef {
  chat_id: string;
  seq: number;
  sender_id: string;
  sent_at?: string;
}

export type MessageStatus = "sending" | "sent" | "failed";

export type MessageType =
  | "text"
  | "image"
  | "file"
  | "audio"
  | "video"
  | "card"
  | "system";

export interface Message {
  chat_id: string;
  seq: number;
  sender_id: string;
  type: MessageType;
  body: string;
  data: { forwarded_from?: ForwardedRef[]; [key: string]: unknown };
  reply_to_seq: number | null;
  mentions: Mention[];
  mentions_all: boolean;
  attachments: Attachment[];
  reactions: Record<string, { count: number; my: boolean }>;
  edited_at: string | null;
  deleted_at: string | null;
  created_at: string;
  _client?: { key: string; status: MessageStatus; error?: string };
}

export interface MessagesPage {
  items: Message[];
  has_more: boolean;
  next_before_seq?: number;
}

export interface Invite {
  id: string;
  chat_id: string;
  code: string;
  url: string;
  uses: number;
  max_uses: number | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface SessionEntry {
  id: string;
  platform: string;
  ip: string | null;
  user_agent: string | null;
  created_at: string;
  last_seen_at: string | null;
  current: boolean;
}

export interface UploadIntent {
  file_id: string;
  upload_url: string;
  method: string;
  headers: Record<string, string>;
  expires_at: string;
  max_size_bytes: number;
}

export interface FileReady {
  id: string;
  status: string;
  av_status: string;
  name: string;
  mime_type: string;
  size_bytes: number;
  thumbnail_url: string | null;
}

export interface SearchMessageItem {
  type: "message";
  chat_id: string;
  seq: number;
  message: Pick<Message, "seq" | "body" | "sender_id" | "created_at">;
}
export interface SearchUserItem {
  type: "user";
  user: Pick<User, "id" | "username" | "full_name" | "title"> & { avatar_url: string | null };
}
export interface SearchChatItem {
  type: "chat";
  chat: Pick<Chat, "id" | "type" | "title">;
}
export type SearchItem = SearchMessageItem | SearchUserItem | SearchChatItem;

export interface AdminStats {
  dau: number;
  messages_per_day: number;
  users_total: number;
  chats_total: number;
  storage_bytes: number;
}

export interface AuditEntry {
  id: number;
  actor_id: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  metadata: Record<string, unknown>;
  ip: string | null;
  created_at: string;
}

export interface WsFrame {
  type: string;
  data?: Record<string, unknown>;
}
