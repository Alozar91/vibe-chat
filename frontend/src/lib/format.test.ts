/** Тесты формат-утилит (время §6, подписи, реакции §6). */

import { describe, expect, it } from 'vitest'
import type { Message, User } from '@/api/types'
import { chatTitle, EMOJI_ORDER, fmtTime, initials, messagePreview, userLabel } from '@/lib/format'

const me: User = {
  id: 'u1',
  username: 'alice',
  display_name: 'alice',
  first_name: 'Алиса',
  last_name: 'Селезнёва',
  email: null,
  avatar_file_id: null,
  is_bot: false,
  is_platform_admin: false,
  time_display: 'browser',
  timezone: null,
  last_seen_at: null,
}

describe('userLabel', () => {
  it('полное имя из first+last', () => {
    expect(userLabel(me)).toBe('Алиса Селезнёва')
  })
  it('fallback на display_name/username', () => {
    expect(userLabel({ ...me, first_name: null, last_name: null })).toBe('alice')
    expect(userLabel(undefined)).toBe('Неизвестно')
  })
})

describe('fmtTime', () => {
  it('UTC-режим добавляет суффикс', () => {
    const t = fmtTime('2026-11-11T12:00:00Z', 'utc', null)
    expect(t).toMatch(/UTC$/)
  })
})

describe('initials', () => {
  it('первые буквы двух слов', () => {
    expect(initials('Алиса Селезнёва')).toBe('АС')
  })
})

describe('chatTitle', () => {
  it('группа — title', () => {
    expect(chatTitle({ type: 'group', title: 'Отдел', members: [] }, 'u1')).toBe('Отдел')
  })
  it('direct — имя собеседника', () => {
    const bob = { ...me, id: 'u2', first_name: 'Боб', last_name: null }
    expect(chatTitle({ type: 'direct', title: null, members: [{ user_id: 'u2', user: bob }] }, 'u1')).toBe('Боб')
  })
})

describe('messagePreview', () => {
  it('удалённое — заглушка', () => {
    const m = { deleted_at: '2026-01-01T00:00:00Z' } as unknown as Message
    expect(messagePreview(m)).toBe('Сообщение удалено')
  })
})

describe('EMOJI_ORDER', () => {
  it('фиксированный набор из 5 (§6)', () => {
    expect(EMOJI_ORDER).toHaveLength(5)
    expect(EMOJI_ORDER).toContain('thumbs_up')
  })
})
