/** Оверлей звонка (§17): входящий/исходящий ринг + панель активного звонка.
 *
 * Рендерится у корня AuthGate; состояние — calls-стор (Zustand).
 * Direct (этап A): таймер, mute, hang-up. Group (этап B): join-модель —
 * активный звонок панели с составом; «Присоединиться» для не-участников.
 * Видео (этап C): kind=video → полноэкранный оверлей с плитками
 * (сетка ≤2×2, дальше — список участников), локальная плитка в углу,
 * камера/шаринг экрана/микрофон/выход.
 */

import { Mic, MicOff, Monitor, MonitorOff, Phone, PhoneOff, Users, Video, VideoOff } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Track } from 'livekit-client'
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

// --- Видео (этап C) ---

/** Видеоплитка: удалённый/локальный трек в <video>; ref-attach по правилам LiveKit. */
function VideoTile({
  identity,
  label,
  isScreen,
  videoVersion,
}: {
  identity: string
  label: string
  isScreen: boolean
  videoVersion: number
}) {
  const room = useCallsStore((s) => s.room)
  const ref = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!room || !el) return
    const participant = identity === 'me' ? room.localParticipant : room.remoteParticipants.get(identity)
    if (!participant) return
    const pub = isScreen ? participant.getTrackPublication(Track.Source.ScreenShare) : participant.getTrackPublication(Track.Source.Camera)
    const track = pub?.videoTrack
    if (track) {
      track.attach(el)
      return () => {
        track.detach(el)
      }
    }
    void videoVersion // перезапуск эффекта при изменении треков
    return undefined
  }, [room, identity, isScreen, videoVersion])

  return (
    <div className="relative overflow-hidden rounded-xl bg-black">
      <video ref={ref} className="h-full w-full object-cover" autoPlay playsInline />
      <span className="absolute bottom-2 left-2 rounded bg-black/60 px-2 py-0.5 text-xs text-white">{label}</span>
    </div>
  )
}

/** Сетка видео: до 8 плиток камер 2×N; шаринг экрана — широко, камеры колонкой. */
function VideoGrid() {
  const room = useCallsStore((s) => s.room)
  const remoteIds = useCallsStore((s) => s.remoteIds)
  const camOn = useCallsStore((s) => s.camOn)
  const screenOn = useCallsStore((s) => s.screenOn)
  const videoVersion = useCallsStore((s) => s.videoVersion)
  const call = useCallsStore((s) => s.current)
  const memberLabels = useCallMembers(call?.participant_ids ?? [])

  if (!room) return null
  const tiles: { identity: string; label: string; isScreen: boolean }[] = []
  if (screenOn) tiles.push({ identity: 'me', label: 'Мой экран', isScreen: true })
  for (const id of remoteIds) {
    const p = room.remoteParticipants.get(id)
    if (!p) continue
    if (p.getTrackPublication(Track.Source.ScreenShare)?.videoTrack) {
      tiles.push({ identity: id, label: `${memberLabels.get(id) ?? id} · экран`, isScreen: true })
    }
  }
  if (camOn) tiles.push({ identity: 'me', label: 'Вы', isScreen: false })
  for (const id of remoteIds) {
    const p = room.remoteParticipants.get(id)
    if (!p) continue
    const camPub = p.getTrackPublication(Track.Source.Camera)
    const camOnRemote = camPub && !camPub.isMuted
    if (camPub?.videoTrack && camOnRemote !== false) {
      tiles.push({ identity: id, label: memberLabels.get(id) ?? id, isScreen: false })
    }
  }

  if (tiles.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-white/70">
        Видео выключено у всех участников
      </div>
    )
  }

  // шаринг экрана (свой или чужой) — широко, остальные плитки узкой колонкой
  const screen = tiles.find((t) => t.isScreen)
  const cams = tiles.filter((t) => !t.isScreen)
  if (screen) {
    return (
      <div className="flex h-full w-full gap-2">
        <div className="min-w-0 flex-1">
          <VideoTile {...screen} videoVersion={videoVersion} />
        </div>
        {cams.length > 0 && (
          <div className="flex w-44 flex-col gap-2 overflow-y-auto">
            {cams.map((t) => (
              <div key={t.identity + String(t.isScreen)} className="aspect-video">
                <VideoTile {...t} videoVersion={videoVersion} />
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }
  const gridCls = cams.length <= 2 ? 'grid-cols-2' : 'grid-cols-2 grid-rows-2'
  return (
    <div className={`grid h-full w-full gap-2 ${gridCls}`}>
      {cams.slice(0, 8).map((t) => (
        <VideoTile key={t.identity + String(t.isScreen)} {...t} videoVersion={videoVersion} />
      ))}
    </div>
  )
}

export function CallOverlay() {
  const call = useCallsStore((s) => s.current)
  const media = useCallsStore((s) => s.media)
  const muted = useCallsStore((s) => s.muted)
  const camOn = useCallsStore((s) => s.camOn)
  const screenOn = useCallsStore((s) => s.screenOn)
  const error = useCallsStore((s) => s.error)
  const accept = useCallsStore((s) => s.accept)
  const reject = useCallsStore((s) => s.reject)
  const cancel = useCallsStore((s) => s.cancel)
  const join = useCallsStore((s) => s.join)
  const leave = useCallsStore((s) => s.leave)
  const toggleMute = useCallsStore((s) => s.toggleMute)
  const toggleCam = useCallsStore((s) => s.toggleCam)
  const toggleScreen = useCallsStore((s) => s.toggleScreen)

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
  const isVideo = call.kind === 'video'
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
        <span className="text-xs text-muted">
          идёт {isVideo ? 'видеозвонок' : 'звонок'} · {call.participant_ids.length} уч.
        </span>
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

  const controls = (big: boolean) => (
    <>
      <button
        onClick={() => void toggleMute()}
        disabled={media !== 'connected'}
        title={muted ? 'Включить микрофон' : 'Выключить микрофон'}
        className={`rounded-full ${big ? 'size-12 bg-white/10 text-white hover:bg-white/20' : 'p-2 text-muted hover:bg-panel-2 hover:text-foreground'} ${muted ? '!bg-red-600/80 !text-white' : ''} disabled:opacity-40`}
      >
        {muted ? <MicOff className={big ? 'size-5' : 'size-4'} /> : <Mic className={big ? 'size-5' : 'size-4'} />}
      </button>
      {isVideo && (
        <>
          <button
            onClick={() => void toggleCam()}
            disabled={media !== 'connected'}
            title={camOn ? 'Выключить камеру' : 'Включить камеру'}
            className={`rounded-full ${big ? 'size-12 bg-white/10 text-white hover:bg-white/20' : 'p-2 text-muted hover:bg-panel-2 hover:text-foreground'} ${!camOn ? '!bg-red-600/80 !text-white' : ''} disabled:opacity-40`}
          >
            {camOn ? <Video className={big ? 'size-5' : 'size-4'} /> : <VideoOff className={big ? 'size-5' : 'size-4'} />}
          </button>
          <button
            onClick={() => void toggleScreen()}
            disabled={media !== 'connected'}
            title={screenOn ? 'Остановить шаринг экрана' : 'Шаринг экрана'}
            className={`rounded-full ${big ? 'size-12 bg-white/10 text-white hover:bg-white/20' : 'p-2 text-muted hover:bg-panel-2 hover:text-foreground'} ${screenOn ? '!bg-accent !text-white' : ''} disabled:opacity-40`}
          >
            {screenOn ? <MonitorOff className={big ? 'size-5' : 'size-4'} /> : <Monitor className={big ? 'size-5' : 'size-4'} />}
          </button>
        </>
      )}
      <button
        onClick={() => void leave()}
        title={isGroup ? 'Выйти из звонка' : 'Завершить'}
        className={`flex items-center justify-center rounded-full bg-red-600 text-white hover:bg-red-500 ${big ? 'size-12' : 'px-3 py-2'}`}
      >
        <PhoneOff className={big ? 'size-5' : 'size-4'} />
      </button>
    </>
  )

  // ринг (direct): карточка «Ответить/Отклонить» — для аудио и видео (этап C);
  // полноэкранный видео-оверлей — только после accept (иначе он перекрывает
  // ринг-карточку у получателя и звонок невозможно принять)
  if (isRinging) {
    return (
      <>
        {error && (
          <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-red-600 px-4 py-2 text-sm text-white shadow-lg">
            {error}
          </div>
        )}
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-80 rounded-2xl border border-border bg-panel p-6 text-center shadow-2xl">
            <div className="mx-auto mb-3 flex size-16 items-center justify-center rounded-full bg-accent text-xl font-semibold text-white">
              {peerLabel.slice(0, 2).toUpperCase()}
            </div>
            <div className="text-sm font-semibold">{peerLabel}</div>
            <div className="mt-1 text-xs text-muted">
              {isInitiator ? (isVideo ? 'Видеовызов…' : 'Вызов…') : isVideo ? 'Входящий видеозвонок' : 'Входящий звонок'}
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
                    onClick={() => void accept(true)}
                    title="Ответить"
                    className="flex size-14 items-center justify-center rounded-full bg-green-600 text-white hover:bg-green-500"
                  >
                    <Phone className="size-6" />
                  </button>
                </>
              )}
            </div>
            {/* видео-звонок: альтернативный ответ только со звуком (§17, паритет с мобильным) */}
            {isVideo && !isInitiator && (
              <button
                onClick={() => void accept(false)}
                className="mt-4 w-full rounded-full border border-border px-3 py-2 text-xs text-muted hover:bg-surface"
              >
                Ответить без видео
              </button>
            )}
          </div>
        </div>
      </>
    )
  }

  if (isVideo) {
    /* Видео (после accept): полноэкранный оверлей с плитками (§17 C) */
    return (
      <div className="fixed inset-0 z-50 flex flex-col bg-zinc-950">
        {error && (
          <div className="absolute left-1/2 top-4 z-10 -translate-x-1/2 rounded-lg bg-red-600 px-4 py-2 text-sm text-white shadow-lg">
            {error}
          </div>
        )}
        <div className="flex items-center gap-3 px-4 py-3 text-white">
          <span className={`size-2.5 rounded-full ${media === 'connected' ? 'bg-green-500' : 'bg-yellow-500 animate-pulse'}`} />
          <span className="text-sm font-medium">{peerLabel}</span>
          {isGroup && <span className="text-xs text-white/60">{call.participant_ids.length} уч.</span>}
          <span className="text-xs text-white/60">{media === 'connected' ? fmtDuration(duration) : 'подключение…'}</span>
        </div>
        <div className="min-h-0 flex-1 px-4">
          {media === 'connected' ? <VideoGrid /> : <div className="flex h-full items-center justify-center text-white/70">Подключение к медиа-серверу…</div>}
        </div>
        <div className="flex items-center justify-center gap-4 py-4">{controls(true)}</div>
      </div>
    )
  }

  /* Активный аудио-звонок: панель (direct — compact; group — с составом) */
  return (
    <>
      {error && (
        <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-red-600 px-4 py-2 text-sm text-white shadow-lg">
          {error}
        </div>
      )}
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
        {controls(false)}
      </div>
    </>
  )
}
