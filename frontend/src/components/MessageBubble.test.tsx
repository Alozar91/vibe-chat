/** Тест MessageBubble: удалённое сообщение рендерит надгробие, реакции группируются. */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Message, User } from '@/api/types'
import { MessageBubble } from './MessageBubble'

const me: User = {
  id: 'u1',
  username: 'alice',
  display_name: 'alice',
  first_name: null,
  last_name: null,
  email: null,
  avatar_file_id: null,
  is_bot: false,
  is_platform_admin: false,
  time_display: 'browser',
  timezone: null,
  last_seen_at: null,
}

function makeMessage(overrides: Partial<Message>): Message {
  return {
    id: 'm1',
    chat_id: 'c1',
    sender_id: 'u2',
    type: 'text',
    text: 'привет',
    payload: null,
    client_ref: null,
    reply_to_id: null,
    forward_from_message_id: null,
    forward_from_chat_id: null,
    forward_snapshot: null,
    created_at: '2026-11-11T12:00:00Z',
    updated_at: '2026-11-11T12:00:00Z',
    timezone: null,
    edited_at: null,
    deleted_at: null,
    reactions: [],
    attachments: [],
    ...overrides,
  }
}

function renderBubble(msg: Message) {
  const qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <MessageBubble
        message={msg}
        isMine={false}
        myId="u1"
        sender={me}
        timeDisplay="browser"
        fixedTz={null}
        replyTarget={undefined}
        onReply={() => {}}
        onEdit={() => {}}
        onForward={() => {}}
      />
    </QueryClientProvider>,
  )
}

describe('MessageBubble', () => {
  it('рендерит текст и автора', () => {
    renderBubble(makeMessage({}))
    expect(screen.getByText('привет')).toBeInTheDocument()
    expect(screen.getByText('alice')).toBeInTheDocument()
  })

  it('удалённое — надгробие без текста (§6)', () => {
    renderBubble(makeMessage({ deleted_at: '2026-11-11T13:00:00Z' }))
    expect(screen.getByText('Сообщение удалено')).toBeInTheDocument()
    expect(screen.queryByText('привет')).not.toBeInTheDocument()
  })

  it('реакции — группы с количеством (§6)', () => {
    renderBubble(
      makeMessage({
        reactions: [
          { emoji: 'thumbs_up', user_ids: ['u1', 'u2'] },
          { emoji: 'fire', user_ids: ['u3'] },
        ],
      }),
    )
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
  })

  it('system-сообщение — по центру без пузыря', () => {
    renderBubble(makeMessage({ type: 'system', text: 'чат создан', sender_id: null }))
    expect(screen.getByText('чат создан')).toBeInTheDocument()
  })

  it('system call_ended — плашка «Звонок» с длительностью (§17)', () => {
    renderBubble(
      makeMessage({
        type: 'system',
        text: 'звонок',
        sender_id: null,
        payload: { kind: 'call_ended', call_id: 'k1', kind_of_call: 'audio', duration_s: 323 },
      }),
    )
    expect(screen.getByText('Звонок')).toBeInTheDocument()
    expect(screen.getByText('· 5:23')).toBeInTheDocument()
    expect(screen.queryByText('звонок')).not.toBeInTheDocument()
  })

  it('system call_missed — плашка «Пропущенный звонок»', () => {
    renderBubble(
      makeMessage({
        type: 'system',
        text: 'пропущенный звонок',
        sender_id: null,
        payload: { kind: 'call_missed', call_id: 'k2', kind_of_call: 'audio' },
      }),
    )
    expect(screen.getByText('Пропущенный звонок')).toBeInTheDocument()
  })
})
