/** Состояние звонка (§17): Zustand, вне TanStack Query — звонок не кэш, а живое состояние.
 *
 * Сигналинг звонка — WS-события call.* (источник истины по статусу);
 * медиа — прямое подключение к LiveKit по room-токену (мимо бэкенда).
 * Ринг-гудки — WebAudio (без ассетов).
 */

import { create } from 'zustand'
import { Room, RoomEvent } from 'livekit-client'
import { callsApi } from '@/api/client'
import type { Call, WsEvent } from '@/api/types'

export type MediaStatus = 'idle' | 'connecting' | 'connected'

interface CallsState {
  /** Звонок, относящийся ко мне (входящий ринг / мой звонок / активный). */
  current: Call | null
  room: Room | null
  media: MediaStatus
  /** identity удалённых участников LiveKit = user_id (§17). */
  remoteIds: string[]
  muted: boolean
  error: string | null
  handleWsEvent: (e: WsEvent) => void
  start: (chatId: string) => Promise<void>
  join: (callId: string) => Promise<void>
  accept: () => Promise<void>
  reject: () => Promise<void>
  cancel: () => Promise<void>
  leave: () => Promise<void>
  toggleMute: () => Promise<void>
  clear: () => void
}

export const useCallsStore = create<CallsState>((set, get) => ({
  current: null,
  room: null,
  media: 'idle',
  remoteIds: [],
  muted: false,
  error: null,

  handleWsEvent: (e) => {
    if (!e.type.startsWith('call.')) return
    const call = (e.data as { call?: Call }).call
    if (!call) return
    const st = get()

    // §17 B: group-звонок — join-модель, ринга нет. Чужой активный звонок
    // в группе: показываем как «баннер в комнате» (current), join — по кнопке
    if (e.type === 'call.ring') {
      // свой ринг-эхо (REST уже установил current) — просто обновляем
      if (st.current?.id === call.id) {
        set({ current: call })
        syncRingtone()
        return
      }
      if (st.current) return // уже в звонке — чужой ринг игнорируем
      set({ current: call })
      syncRingtone()
      return
    }

    if (e.type === 'call.joined') {
      // я уже в этом звонке (REST установил current) — обновить состав
      if (st.current?.id === call.id) {
        set({ current: call })
        return
      }
      // чужой group-звонок: показать панель «идёт звонок» (ring-оверлея нет)
      if (st.current) return
      set({ current: call })
      return
    }

    // остальные события касаются только текущего звонка
    if (st.current?.id !== call.id) return
    if (call.status === 'ended') {
      get().clear()
      return
    }
    set({ current: call })
    syncRingtone()
  },

  start: async (chatId) => {
    if (get().current) {
      set({ error: 'уже в звонке' })
      return
    }
    set({ error: null })
    try {
      const call = await callsApi.start(chatId)
      set({ current: call })
      await connectMedia()
    } catch (err) {
      set({ current: null, error: errMessage(err) })
    }
  },

  join: async (callId) => {
    // §17 B: current может быть уже установлен баннером чужого group-звонка —
    // блокируем только join *другого* звонка
    const cur = get().current
    if (cur && cur.id !== callId) {
      set({ error: 'уже в звонке' })
      return
    }
    set({ error: null })
    try {
      const call = await callsApi.join(callId)
      set({ current: call })
      await connectMedia()
    } catch (err) {
      set({ error: errMessage(err) })
    }
  },

  accept: async () => {
    const call = get().current
    if (!call) return
    set({ error: null })
    try {
      const updated = await callsApi.accept(call.id)
      set({ current: updated })
      syncRingtone()
      await connectMedia()
    } catch (err) {
      set({ error: errMessage(err) })
    }
  },

  reject: async () => {
    const call = get().current
    if (!call) return
    try {
      await callsApi.reject(call.id)
      get().clear()
    } catch (err) {
      set({ error: errMessage(err) })
    }
  },

  cancel: async () => {
    const call = get().current
    if (!call) return
    try {
      await callsApi.cancel(call.id)
      get().clear()
    } catch (err) {
      set({ error: errMessage(err) })
    }
  },

  leave: async () => {
    const call = get().current
    if (!call) return
    try {
      await callsApi.leave(call.id)
      get().clear()
    } catch (err) {
      set({ error: errMessage(err) })
    }
  },

  toggleMute: async () => {
    const room = get().room
    if (!room) return // медиа ещё не подключено — mute недоступен (кнопка задизейблена)
    const next = !get().muted
    await room.localParticipant.setMicrophoneEnabled(!next)
    set({ muted: next })
  },

  clear: () => {
    stopRingtone()
    const room = get().room
    if (room) room.disconnect()
    set({ current: null, room: null, media: 'idle', remoteIds: [], muted: false, error: null })
  },
}))

function errMessage(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err)
  if (msg.includes('503')) return 'звонки не настроены на сервере'
  if (msg.includes('409')) return 'другой звонок уже идёт'
  return `не удалось: ${msg}`
}

// --- LiveKit-подключение (медиа, §17) ---

async function connectMedia(): Promise<void> {
  const { current, room } = useCallsStore.getState()
  if (!current || room) return // уже подключены (инициатор подключается на start)
  useCallsStore.setState({ media: 'connecting' })
  try {
    const { token, ws_url } = await callsApi.token(current.id)
    const lkRoom = new Room({ adaptiveStream: true, dynacast: true })
    const syncRemote = () => {
      if (useCallsStore.getState().room !== lkRoom) return
      useCallsStore.setState({ remoteIds: Array.from(lkRoom.remoteParticipants.keys()) })
    }
    lkRoom.on(RoomEvent.ParticipantConnected, syncRemote)
    lkRoom.on(RoomEvent.ParticipantDisconnected, syncRemote)
    // удалённый звук/видео нужно явно проигрывать: без attach() треки
    // подписываются, но в DOM не попадают → тишина (набл. 2026-11-18)
    lkRoom.on(RoomEvent.TrackSubscribed, (track) => {
      track.attach()
    })
    lkRoom.on(RoomEvent.TrackUnsubscribed, (track) => {
      track.detach()
    })
    lkRoom.on(RoomEvent.Disconnected, () => {
      if (useCallsStore.getState().room === lkRoom) {
        useCallsStore.setState({ media: 'idle', remoteIds: [] })
      }
    })
    await lkRoom.connect(ws_url, token)
    await lkRoom.localParticipant.setMicrophoneEnabled(true)
    useCallsStore.setState({
      room: lkRoom,
      media: 'connected',
      remoteIds: Array.from(lkRoom.remoteParticipants.keys()),
    })
  } catch {
    // сигналинг-звонок жив; медиа недоступно (например, LiveKit не запущен)
    useCallsStore.setState({ media: 'idle', error: 'медиа-сервер недоступен' })
  }
}

// --- Ринг-гудки: WebAudio, без звуковых файлов ---

let ringCtx: AudioContext | null = null
let ringTimer: ReturnType<typeof setInterval> | null = null

function ringBeep(ctx: AudioContext): void {
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.frequency.value = 440
  gain.gain.value = 0.06
  osc.connect(gain)
  gain.connect(ctx.destination)
  osc.start()
  osc.stop(ctx.currentTime + 0.3)
}

function startRingtone(): void {
  if (ringTimer) return
  try {
    ringCtx = ringCtx ?? new AudioContext()
    ringBeep(ringCtx)
    ringTimer = setInterval(() => {
      if (ringCtx) ringBeep(ringCtx)
    }, 2000)
  } catch {
    // нет AudioContext (тесты) — без звука
  }
}

function stopRingtone(): void {
  if (ringTimer) {
    clearInterval(ringTimer)
    ringTimer = null
  }
}

/** Гудок, пока звонок в ringing (и входящий, и мой исходящий — КПВ). */
function syncRingtone(): void {
  const call = useCallsStore.getState().current
  if (call && call.status === 'ringing') startRingtone()
  else stopRingtone()
}
