/** Типы API (/api/v1) — контракты бэкенда (Docs/concept.md §12). */

export interface User {
  id: string
  username: string
  display_name: string
  first_name: string | null
  last_name: string | null
  email: string | null
  avatar_file_id: string | null
  is_bot: boolean
  is_platform_admin: boolean
  time_display: 'browser' | 'as_sent' | 'fixed' | 'utc'
  timezone: string | null
  last_seen_at: string | null
}

export interface ChatMember {
  user_id: string
  role: 'owner' | 'admin' | 'member'
  last_read_message_id: string | null
  user?: User
}

export interface Chat {
  id: string
  type: 'direct' | 'group'
  title: string | null
  last_message_at: string | null
  unread_count: number
}

export interface ChatDetails extends Chat {
  members: ChatMember[]
}

export interface ReactionGroup {
  emoji: string
  user_ids: string[]
}

export interface Attachment {
  id: string
  kind: 'image' | 'video' | 'file'
  file_id: string
  name: string | null
  size_bytes: number | null
  url: string
  thumb_url: string | null
}

export interface Message {
  id: string
  chat_id: string
  sender_id: string | null
  type: 'text' | 'system'
  text: string | null
  payload: Record<string, unknown> | null
  client_ref: string | null
  reply_to_id: string | null
  forward_from_message_id: string | null
  forward_from_chat_id: string | null
  forward_snapshot: { display_name?: string } | null
  created_at: string
  updated_at: string
  timezone: string | null
  edited_at: string | null
  deleted_at: string | null
  reactions: ReactionGroup[]
  attachments: Attachment[]
}

export interface Invite {
  id: string
  max_uses: number | null
  uses_count: number
  expires_at: string | null
  deactivated_at: string | null
  created_at: string
}

export interface InviteCreated extends Invite {
  code: string
}

export interface FileOut {
  id: string
  status: 'pending' | 'ready'
  size_bytes: number
  mime_type: string
  real_mime_type: string | null
  thumb_key: string | null
  blurhash: string | null
  sha256: string
  created_at: string
}

/** WS-конверт (§9). */
export type WsEvent =
  | { type: 'message.new'; data: { message: Message }; event_id: string; ts: number }
  | { type: 'message.edited'; data: { message: Message }; event_id: string; ts: number }
  | { type: 'message.deleted'; data: { message: Message }; event_id: string; ts: number }
  | {
      type: 'reaction.updated'
      data: { message_id: string; chat_id: string; reactions: ReactionGroup[] }
      event_id: string
      ts: number
    }
  | { type: 'chat.created'; data: { chat: Chat }; event_id: string; ts: number }
  | { type: 'chat.updated'; data: { chat: Chat; deleted?: boolean }; event_id: string; ts: number }
  | { type: 'member.joined'; data: { chat_id: string; user: User }; event_id: string; ts: number }
  | { type: 'member.left'; data: { chat_id: string; user_id: string }; event_id: string; ts: number }
  | { type: 'typing'; data: { chat_id: string; user_id: string }; event_id: string; ts: number }
  | {
      type: 'presence'
      data: { user_id: string; online: boolean; last_seen_at: string | null }
      event_id: string
      ts: number
    }
  | {
      type: 'read'
      data: { chat_id: string; user_id: string; last_read_message_id: string }
      event_id: string
      ts: number
    }
  | { type: string; data: unknown; event_id: string; ts: number }
