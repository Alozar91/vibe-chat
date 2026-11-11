/** Утилиты отображения (время — §6 «Время и часовые пояса», аватары, реакции). */

import type { Message, User } from '@/api/types'

export const EMOJI: Record<string, string> = {
  thumbs_up: '👍',
  heart: '❤️',
  laugh: '😂',
  fire: '🔥',
  check: '✅',
}

export const EMOJI_ORDER = ['thumbs_up', 'heart', 'laugh', 'fire', 'check'] as const

export function fmtTime(iso: string, mode: User['time_display'], fixedTz: string | null): string {
  const d = new Date(iso)
  const opts: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' }
  switch (mode) {
    case 'utc':
      return d.toLocaleTimeString(undefined, { ...opts, timeZone: 'UTC' }) + ' UTC'
    case 'as_sent':
      return d.toLocaleTimeString(undefined, { ...opts, timeZone: fixedTz ?? undefined })
    case 'fixed':
      return d.toLocaleTimeString(undefined, { ...opts, timeZone: fixedTz ?? undefined })
    default:
      return d.toLocaleTimeString(undefined, opts)
  }
}

export function fmtDateTime(iso: string, mode: User['time_display'], fixedTz: string | null): string {
  const d = new Date(iso)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const time = fmtTime(iso, mode, fixedTz)
  if (sameDay) return time
  const date = d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
  return `${date} ${time}`
}

export function userLabel(u: User | undefined | null): string {
  if (!u) return 'Неизвестно'
  const full = [u.first_name, u.last_name].filter(Boolean).join(' ').trim()
  return full || u.display_name || u.username
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return name.slice(0, 2).toUpperCase()
}

export function chatTitle(
  chat: { type: string; title: string | null; members?: { user?: User; user_id: string }[] },
  meId: string,
): string {
  if (chat.type === 'group') return chat.title ?? 'Группа'
  const other = chat.members?.find((m) => m.user_id !== meId)?.user
  return other ? userLabel(other) : 'Личный чат'
}

export function messagePreview(m: Message | null | undefined): string {
  if (!m) return ''
  if (m.deleted_at) return 'Сообщение удалено'
  if (m.type === 'system') return m.text ?? ''
  const att = m.attachments[0]
  const prefix = att ? (att.kind === 'image' ? '🖼 ' : att.kind === 'video' ? '🎬 ' : '📎 ') : ''
  return prefix + (m.text ?? (att ? att.name ?? 'Вложение' : ''))
}

/** IANA-пояс браузера для messages.timezone (§6). */
export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone
  } catch {
    return 'UTC'
  }
}
