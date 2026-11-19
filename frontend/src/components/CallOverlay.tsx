/** Оверлей звонка (§17): входящий/исходящий ринг + панель активного звонка.
 *
 * Рендерится у корня AuthGate; состояние — calls-стор (Zustand).
 * Direct (этап A): таймер, mute, hang-up. Group (этап B): join-модель —
 * активный звонок панели с составом; «Присоединиться» для не-участников;
 * ring-оверлей у группы отсутствует (комната открыта без ринга, §17).
 */

import { Mic, MicOff, Phone, PhoneOff, Users } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { chatsApi, usersApi } from '@/api/client'
import { useCallsStore } from '@/realtime/calls'
import { userLabel } from '@/lib/format'

function useCallDuration(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  return now
}

function fmtDuration(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

/** Имя собеседника для direct / названия группы для group. */
function useCallPeerLabel(chatId: string | null, initiatorId: string | null, myId: string): string {
  const chat = useQuery({
    queryKey: ['chat', chatId],
    queryFn: () => chatsApi.get(chatId!),
    enabled: !!chatId,
  })
  if (!chatId || !initiatorId) return 'Звонок'
  const members = chat.data?.members ?? []
  const peer = chat.data?.type === 'direct' ? members.find((m) => m.user_id !== myId)?.user : undefined
  const label = peer
    ? userLabel(peer)
    : chat.data?.type === 'group'
      ? (chat.data.title ?? 'Группа')
      : userLabel(members.find((m) => m.user_id === initiatorId)?.user)
  return label || 'Звонок'
}

/** Признак group-чата звонка (join-модель §17 B / ringing §17 A). */
function useCallIsGroup(chatId: string | null): boolean {
  const chat = useQuery({
    queryKey: ['chat', chatId],
    queryFn: () => chatsApi.get(chatId!),
    enabled: !!chatId,
  })
  return chat.data?.type === 'group'
}

/** Состав звонка: user_id → подпись (из members чата звонка). */
function useCallMembers(participantIds: string[]): Map<string, string> {
  const labels = new Map<string, string>()
  const chatId = useCallsStore((s) => s.current?.chat_id ?? null)
  const chat = useQuery({
    queryKey: ['chat', chatId],
    queryFn: () => chatsApi.get(chatId!),
    enabled: !!chatId,
  })
  for (const id of participantIds) {
    const m = chat.data?.members.find((mm) => mm.user_id === id)
    labels.set(id, m ? userLabel(m.user) : id.slice(0, 8))
  }
  return labels
}

export function CallOverlay() {
  const call = useCallsStore((s) => s.current)
  const media = useCallsStore((s) => s.media)
  const muted = useCallsStore((s) => s.muted)
  const error = useCallsStore((s) => s.error)
  const accept = useCallsStore((s) => s.accept)
  const reject = useCallsStore((s) => s.reject)
  const cancel = useCallsStore((s) => s.cancel)
  const join = useCallsStore((s) => s.join)
  const leave = useCallsStore((s) => s.leave)
  const toggleMute = useCallsStore((s) => s.toggleMute)

  // мой локальный id (§5): User.id — не KC sub; кэш ['me'] прогревается ChatPage
  const me = useQuery({ queryKey: ['me'], queryFn: usersApi.me, staleTime: Infinity })
  const myId = me.data?.id ?? ''

  const tick = useCallDuration()
  const peerLabel = useCallPeerLabel(call?.chat_id ?? null, call?.initiator_id ?? null, myId)
  const memberLabels = useCallMembers(call?.participant_ids ?? [])
  const isGroupChat = useCallIsGroup(call?.chat_id ?? null)

  if (!call) {
    return error ? (
      <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-red-600 px-4 py-2 text-sm text-white shadow-lg">
        {error}
      </div>
    ) : null
  }

  const isGroup = isGroupChat
  const iAmIn = call.participant_ids.includes(myId)
  const isRinging = call.status === 'ringing'
  const isInitiator = call.initiator_id === myId
  const durationStart = call.started_at ? new Date(call.started_at).getTime() : null
  const duration = durationStart ? Math.max(0, Math.floor((tick - durationStart) / 1000)) : 0

  // §17 B: чужой group-звонок, я не в комнате — баннер «идёт звонок», join по кнопке
  if (isGroup && !iAmIn && call.status !== 'ended') {
    return (
      <div className="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-full border border-border bg-panel px-4 py-2 shadow-xl">
        <Users className="size-4 text-accent" />
        <span className="text-sm font-medium">{peerLabel}</span>
        <span className="text-xs text-muted">идёт звонок · {call.participant_ids.length} уч.</span>
        <button
          onClick={() => void join(call.id)}
          title="Присоединиться"
          className="flex items-center gap-1 rounded-full bg-green-600 px-3 py-2 text-xs font-medium text-white hover:bg-green-500"
        >
          <Phone className="size-4" />
          Присоединиться
        </button>
      </div>
    )
  }

  return (
    <>
      {error && (
        <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-red-600 px-4 py-2 text-sm text-white shadow-lg">
          {error}
        </div>
      )}
      {isRinging ? (
        /* Ринг: карточка по центру (только direct — §17 B) */
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-80 rounded-2xl border border-border bg-panel p-6 text-center shadow-2xl">
            <div className="mx-auto mb-3 flex size-16 items-center justify-center rounded-full bg-accent text-xl font-semibold text-white">
              {peerLabel.slice(0, 2).toUpperCase()}
            </div>
            <div className="text-sm font-semibold">{peerLabel}</div>
            <div className="mt-1 text-xs text-muted">
              {isInitiator ? 'Вызов…' : 'Входящий звонок'}
            </div>
            <div className="mt-5 flex justify-center gap-6">
              {isInitiator ? (
                <button
                  onClick={() => void cancel()}
                  title="Отменить"
                  className="flex size-14 items-center justify-center rounded-full bg-red-600 text-white hover:bg-red-500"
                >
                  <PhoneOff className="size-6" />
                </button>
              ) : (
                <>
                  <button
                    onClick={() => void reject()}
                    title="Отклонить"
                    className="flex size-14 items-center justify-center rounded-full bg-red-600 text-white hover:bg-red-500"
                  >
                    <PhoneOff className="size-6" />
                  </button>
                  <button
                    onClick={() => void accept()}
                    title="Ответить"
                    className="flex size-14 items-center justify-center rounded-full bg-green-600 text-white hover:bg-green-500"
                  >
                    <Phone className="size-6" />
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      ) : (
        /* Активный звонок: панель (direct — compact; group — с составом) */
        <div className="fixed bottom-4 right-4 z-50 flex items-center gap-3 rounded-full border border-border bg-panel px-4 py-2 shadow-xl">
          <span className="flex size-2.5 items-center justify-center">
            <span className={`size-2.5 rounded-full ${media === 'connected' ? 'bg-green-500' : 'bg-yellow-500 animate-pulse'}`} />
          </span>
          <span className="text-sm font-medium">{peerLabel}</span>
          {isGroup && (
            <span className="max-w-[240px] truncate text-xs text-muted" title={call.participant_ids.map((id) => memberLabels.get(id) ?? id).join(', ')}>
              {call.participant_ids.length} уч.: {call.participant_ids.map((id) => memberLabels.get(id) ?? id).join(', ')}
            </span>
          )}
          <span className="text-xs text-muted">
            {media === 'connected' ? fmtDuration(duration) : 'подключение…'}
          </span>
          <button
            onClick={() => void toggleMute()}
            disabled={media !== 'connected'}
            title={muted ? 'Включить микрофон' : 'Выключить микрофон'}
            className={`rounded-full p-2 ${muted ? 'bg-red-600/80 text-white' : 'text-muted hover:bg-panel-2 hover:text-foreground'} disabled:opacity-40`}
          >
            {muted ? <MicOff className="size-4" /> : <Mic className="size-4" />}
          </button>
          <button
            onClick={() => void leave()}
            title={isGroup ? 'Выйти из звонка' : 'Завершить'}
            className="flex items-center gap-1 rounded-full bg-red-600 px-3 py-2 text-xs text-white hover:bg-red-500"
          >
            <PhoneOff className="size-4" />
          </button>
        </div>
      )}
    </>
  )
}
