/** Пузырь сообщения: текст/вложения, цитата, реакции, меню (reply/edit/delete/react). */

import { useMutation } from '@tanstack/react-query'
import { Forward, MoreVertical, Pencil, Reply, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { messagesApi } from '@/api/client'
import type { Message, User } from '@/api/types'
import { EMOJI, EMOJI_ORDER, fmtDateTime, userLabel } from '@/lib/format'

interface Props {
  message: Message
  isMine: boolean
  myId: string
  sender: User | undefined
  timeDisplay: User['time_display']
  fixedTz: string | null
  replyTarget: Message | undefined
  onReply: () => void
  onEdit: () => void
  onForward: () => void
}

export function MessageBubble({
  message: m,
  isMine,
  myId,
  sender,
  timeDisplay,
  fixedTz,
  replyTarget,
  onReply,
  onEdit,
  onForward,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [reactbarOpen, setReactbarOpen] = useState(false)

  const react = useMutation({
    mutationFn: (emoji: string) => messagesApi.react(m.id, emoji),
  })

  const deleteMsg = useMutation({
    mutationFn: () => messagesApi.delete(m.id),
  })

  if (m.type === 'system') {
    // плашка звонка (§17): «📞 Звонок · 5:23» / «📞 Пропущенный звонок»
    const kind = m.payload?.['kind']
    if (kind === 'call_ended' || kind === 'call_missed') {
      const p = m.payload as { duration_s?: number; kind_of_call?: string }
      const minutes = Math.floor((p.duration_s ?? 0) / 60)
      const seconds = (p.duration_s ?? 0) % 60
      const duration = `${minutes}:${String(seconds).padStart(2, '0')}`
      return (
        <div className="my-2 flex justify-center">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-panel-2 px-3 py-1 text-xs text-muted">
            <span>{kind === 'call_missed' ? '📵' : '📞'}</span>
            <span>{kind === 'call_missed' ? 'Пропущенный звонок' : 'Звонок'}</span>
            {kind === 'call_ended' && p.duration_s !== undefined && <span>· {duration}</span>}
            {p.kind_of_call === 'video' && <span>· видео</span>}
          </span>
        </div>
      )
    }
    return <div className="my-2 text-center text-xs text-muted">{m.text}</div>
  }

  const deleted = m.deleted_at !== null
  // все картинки сеткой; файлы — списком карточек (§8: до 10 вложений)
  const images = !deleted ? m.attachments.filter((a) => a.kind === 'image') : []
  const files = !deleted ? m.attachments.filter((a) => a.kind !== 'image') : []

  return (
    <div className={`group my-1 flex gap-2 ${isMine ? 'justify-end' : 'justify-start'}`}>
      {!isMine && (
        <div className="mt-auto flex size-7 shrink-0 items-center justify-center rounded-full bg-accent text-[10px] font-semibold text-white">
          {userLabel(sender).slice(0, 2).toUpperCase()}
        </div>
      )}

      <div className={`relative max-w-[70%] rounded-xl px-3 py-2 text-sm ${isMine ? 'bg-bubble-out' : 'bg-bubble-in'}`}>
        {!isMine && (
          <div className="mb-0.5 text-xs font-semibold text-accent">{userLabel(sender)}</div>
        )}

        {/* Пересланное из */}
        {m.forward_from_message_id && (
          <div className="mb-1 border-l-2 border-muted pl-2 text-xs text-muted">
            Переслано от {m.forward_snapshot?.display_name ?? 'неизвестно'}
          </div>
        )}

        {/* Цитата */}
        {m.reply_to_id && (
          <div className="mb-1 border-l-2 border-accent pl-2 text-xs text-muted">
            {replyTarget
              ? replyTarget.deleted_at
                ? 'сообщение удалено'
                : replyTarget.text ?? 'вложение'
              : 'цитируемое сообщение'}
          </div>
        )}

        {/* Контент */}
        {deleted ? (
          <span className="italic text-muted">Сообщение удалено</span>
        ) : (
          <>
            {images.length > 0 && (
              <div className={`mb-1 grid gap-1 ${images.length === 1 ? 'grid-cols-1' : 'grid-cols-2'}`}>
                {images.map((a, i) => (
                  <a key={a.url ?? i} href={a.url} target="_blank" rel="noreferrer">
                    <img
                      src={a.thumb_url ?? a.url}
                      alt={a.name ?? ''}
                      className="max-h-64 w-full rounded-lg object-cover"
                    />
                  </a>
                ))}
              </div>
            )}
            {files.map((a) => (
              <a
                key={a.url ?? a.name}
                href={a.url}
                target="_blank"
                rel="noreferrer"
                className="mb-1 flex items-center gap-2 rounded-lg bg-black/20 px-2 py-1.5 hover:bg-black/30"
              >
                <span>{a.kind === 'video' ? '🎬' : '📎'}</span>
                <span className="truncate underline">{a.name ?? 'файл'}</span>
              </a>
            ))}
            {m.text && <span className="whitespace-pre-wrap break-words">{m.text}</span>}
          </>
        )}

        {/* Реакции (§6): клик по группе — toggle моей реакции */}
        {!deleted && m.reactions.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {m.reactions.map((g) => (
              <button
                key={g.emoji}
                onClick={() => react.mutate(g.emoji)}
                title={g.user_ids.join(', ')}
                className={`flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-xs ${
                  g.user_ids.includes(myId) ? 'bg-accent/40' : 'bg-black/25'
                } hover:bg-black/40`}
              >
                <span>{EMOJI[g.emoji] ?? g.emoji}</span>
                <span>{g.user_ids.length}</span>
              </button>
            ))}
          </div>
        )}

        <div className="mt-0.5 text-right text-[10px] text-muted/70">
          {m.edited_at && 'изменено '}
          {fmtDateTime(m.created_at, timeDisplay, fixedTz)}
        </div>

        {/* Панель действий при hover */}
        {!deleted && (
          <div
            className={`absolute top-1 ${isMine ? 'left-0 -translate-x-full' : 'right-0 translate-x-full'} hidden gap-0.5 rounded-lg border border-border bg-panel p-0.5 group-hover:flex`}
          >
            <button title="Реакция" onClick={() => setReactbarOpen((v) => !v)} className="rounded p-1 hover:bg-panel-2">
              <span className="text-sm">🙂</span>
            </button>
            <button title="Ответить" onClick={onReply} className="rounded p-1 hover:bg-panel-2">
              <Reply className="size-3.5" />
            </button>
            {isMine && (
              <button title="Редактировать" onClick={onEdit} className="rounded p-1 hover:bg-panel-2">
                <Pencil className="size-3.5" />
              </button>
            )}
            <button title="Переслать" onClick={onForward} className="rounded p-1 hover:bg-panel-2">
              <Forward className="size-3.5" />
            </button>
            <button
              title="Удалить"
              onClick={() => deleteMsg.mutate()}
              className="rounded p-1 hover:bg-panel-2"
            >
              <Trash2 className="size-3.5" />
            </button>
            <button title="Ещё" onClick={() => setMenuOpen((v) => !v)} className="rounded p-1 hover:bg-panel-2">
              <MoreVertical className="size-3.5" />
            </button>
          </div>
        )}

        {/* Панель выбора реакции (§6) */}
        {reactbarOpen && (
          <div
            className={`absolute z-10 flex gap-1 rounded-lg border border-border bg-panel px-2 py-1 shadow-lg ${isMine ? 'right-0' : 'left-0'} -top-10`}
          >
            {EMOJI_ORDER.map((name) => (
              <button
                key={name}
                onClick={() => {
                  react.mutate(name)
                  setReactbarOpen(false)
                }}
                className="rounded p-1 text-lg hover:bg-panel-2"
              >
                {EMOJI[name]}
              </button>
            ))}
          </div>
        )}

        {menuOpen && (
          <div className="absolute right-0 top-full z-10 mt-1 rounded-lg border border-border bg-panel py-1 text-xs shadow-lg">
            <button
              onClick={() => {
                void navigator.clipboard.writeText(m.id)
                setMenuOpen(false)
              }}
              className="block w-full px-3 py-1.5 text-left hover:bg-panel-2"
            >
              Копировать ID
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
