/**
 * Стор звонков (§3.12): порт вебового frontend/src/realtime/calls.ts.
 * Сигналинг — WS-события call.* (источник истины по статусу, §17);
 * мутации — REST; медиа — прямое подключение к LiveKit по room-токену.
 * Zustand вне TanStack Query — звонок не кэш, а живое состояние.
 */

import { AudioSession } from "@livekit/react-native";
import { create } from "zustand";
import { Room, RoomEvent } from "livekit-client";
import { PermissionsAndroid, Platform, Vibration, type Permission } from "react-native";
import { callsApi } from "../api/endpoints";
import type { Call } from "../api/types";
import { config } from "../services/config";
import { ringPlayer } from "../services/ring";

export type MediaStatus = "idle" | "connecting" | "connected";

interface CallsState {
  /** Звонок, относящийся ко мне (входящий ринг / мой звонок / активный). */
  current: Call | null;
  room: Room | null;
  media: MediaStatus;
  /** identity удалённых участников LiveKit = user_id (§17). */
  remoteIds: string[];
  muted: boolean;
  /** Камера (этап 10, видео). */
  camOn: boolean;
  /** Громкая связь; default — earpiece у аудио-звонков. */
  speakerOn: boolean;
  error: string | null;

  handleWsEvent: (type: string, data: unknown) => void;
  start: (chatId: string, kind?: "audio" | "video") => Promise<void>;
  join: (callId: string) => Promise<void>;
  accept: () => Promise<void>;
  reject: () => Promise<void>;
  cancel: () => Promise<void>;
  leave: () => Promise<void>;
  toggleMute: () => Promise<void>;
  toggleCam: () => Promise<void>;
  toggleSpeaker: () => Promise<void>;
  clear: () => void;
}

/** Авто-скрытие тоста ошибки: без него ошибка «401 при истёкшем токене» висит вечно. */
let errorTimer: ReturnType<typeof setTimeout> | null = null;
const ERROR_TTL_MS = 4000;

function setErrorState(error: string | null) {
  if (errorTimer) clearTimeout(errorTimer);
  useCalls.setState({ error });
  if (error) {
    errorTimer = setTimeout(() => {
      errorTimer = null;
      if (useCalls.getState().error === error) useCalls.setState({ error: null });
    }, ERROR_TTL_MS);
  }
}

export const useCalls = create<CallsState>((set, get) => ({
  current: null,
  room: null,
  media: "idle",
  remoteIds: [],
  muted: false,
  camOn: false,
  speakerOn: false,
  error: null,

  handleWsEvent: (type, data) => {
    if (!type.startsWith("call.")) return;
    const call = (data as { call?: Call }).call;
    if (!call) return;
    const st = get();

    // §17 A: входящий ринг direct / свой ринг-эхо после REST start
    if (type === "call.ring") {
      if (st.current?.id === call.id) {
        set({ current: call });
        syncRing();
        return;
      }
      if (st.current) return; // уже в звонке — чужой ринг игнорируем
      set({ current: call });
      syncRing();
      return;
    }

    // §17 B: групповой звонок — join-модель; чужой активный звонок в группе
    // показываем баннером «идёт звонок» (join — по кнопке)
    if (type === "call.joined") {
      if (st.current?.id === call.id) {
        set({ current: call });
        return;
      }
      if (st.current) return;
      set({ current: call });
      return;
    }

    // остальные события касаются только текущего звонка
    if (st.current?.id !== call.id) return;
    if (call.status === "ended") {
      get().clear();
      return;
    }
    set({ current: call });
    syncRing();
  },

  start: async (chatId, kind = "audio") => {
    if (get().current) {
      setErrorState("err_in_call");
      return;
    }
    setErrorState(null);
    try {
      await ensureMicPermission();
      const call = await callsApi.start(chatId, kind);
      set({ current: call });
      await connectMedia();
    } catch (err) {
      set({ current: null });
      setErrorState(errMessage(err));
    }
  },

  join: async (callId) => {
    // current может быть уже установлен баннером чужого group-звонка —
    // блокируем только join *другого* звонка
    const cur = get().current;
    if (cur && cur.id !== callId) {
      setErrorState("err_in_call");
      return;
    }
    setErrorState(null);
    try {
      await ensureMicPermission();
      const call = await callsApi.join(callId);
      set({ current: call });
      await connectMedia();
    } catch (err) {
      setErrorState(errMessage(err));
    }
  },

  accept: async () => {
    const call = get().current;
    if (!call) return;
    setErrorState(null);
    try {
      await ensureMicPermission();
      const updated = await callsApi.accept(call.id);
      set({ current: updated });
      syncRing();
      await connectMedia();
    } catch (err) {
      setErrorState(errMessage(err));
    }
  },

  reject: async () => {
    const call = get().current;
    if (!call) return;
    try {
      await callsApi.reject(call.id);
      get().clear();
    } catch (err) {
      setErrorState(errMessage(err));
    }
  },

  cancel: async () => {
    const call = get().current;
    if (!call) return;
    try {
      await callsApi.cancel(call.id);
      get().clear();
    } catch (err) {
      setErrorState(errMessage(err));
    }
  },

  leave: async () => {
    const call = get().current;
    if (!call) return;
    try {
      await callsApi.leave(call.id);
      get().clear();
    } catch (err) {
      setErrorState(errMessage(err));
    }
  },

  toggleMute: async () => {
    const room = get().room;
    if (!room) return; // медиа ещё не подключено — кнопка задизейблена
    const next = !get().muted;
    await room.localParticipant.setMicrophoneEnabled(!next);
    set({ muted: next });
  },

  toggleCam: async () => {
    const room = get().room;
    if (!room) return;
    const next = !get().camOn;
    await room.localParticipant.setCameraEnabled(next);
    set({ camOn: next });
  },

  toggleSpeaker: async () => {
    const next = !get().speakerOn;
    await AudioSession.selectAudioOutput(next ? "speaker" : "earpiece");
    set({ speakerOn: next });
  },

  clear: () => {
    ringPlayer.stop();
    Vibration.cancel();
    const room = get().room;
    if (room) room.disconnect().catch(() => {});
    void AudioSession.stopAudioSession();
    set({
      current: null,
      room: null,
      media: "idle",
      remoteIds: [],
      muted: false,
      camOn: false,
      speakerOn: false,
      error: null,
    });
  },
}));

function errMessage(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  if (msg.includes("503")) return "err_calls_not_configured";
  if (msg.includes("409")) return "err_other_call";
  if (msg.includes("404")) return "err_call_gone";
  if (msg.includes("403")) return "err_no_access";
  if (msg.includes("permission")) return "err_mic_denied";
  return "err_generic";
}

/** Ринг: гудок лупом, пока звонок в ringing (и входящий, и мой исходящий). */
function syncRing(): void {
  const call = useCalls.getState().current;
  if (call && call.status === "ringing") ringPlayer.start();
  else {
    ringPlayer.stop();
    Vibration.cancel();
  }
}

/** RECORD_AUDIO — runtime-разрешение Android 6+; отказ → ошибка в сторе. */
async function ensureMicPermission(): Promise<void> {
  if (Platform.OS !== "android") return;
  const perm = PermissionsAndroid.PERMISSIONS.RECORD_AUDIO as Permission;
  const has = await PermissionsAndroid.check(perm);
  if (has) return;
  const res = await PermissionsAndroid.request(perm, {
    title: "Микрофон",
    message: "Vibe Chat нужен доступ к микрофону для звонков",
    buttonPositive: "OK",
  });
  if (res !== PermissionsAndroid.RESULTS.GRANTED) {
    throw new Error("permission denied");
  }
}

// --- LiveKit-подключение (медиа, §17) ---

async function connectMedia(): Promise<void> {
  const { current, room } = useCalls.getState();
  if (!current || room) return; // уже подключены (инициатор подключается на start)
  useCalls.setState({ media: "connecting" });
  try {
    const { token, ws_url } = await callsApi.token(current.id);
    // EXPO_PUBLIC_LIVEKIT_URL — dev-override (в эмуляторе localhost не резолвится, §3.12)
    const url = config.livekitUrl ?? ws_url;
    const lkRoom = new Room({ adaptiveStream: true, dynacast: true });
    const isCurrent = () => useCalls.getState().room === lkRoom || useCalls.getState().room === null;

    const syncRemote = () => {
      if (!isCurrent()) return;
      useCalls.setState({ remoteIds: Array.from(lkRoom.remoteParticipants.keys()) });
    };
    lkRoom.on(RoomEvent.ParticipantConnected, syncRemote);
    lkRoom.on(RoomEvent.ParticipantDisconnected, syncRemote);
    lkRoom.on(RoomEvent.Disconnected, () => {
      // сервер закрыл комнату (конец звонка) — стор чистит WS-событие call.ended;
      // здесь — страховка, если событие потерялось
      if (useCalls.getState().room === lkRoom) {
        useCalls.setState({ media: "idle", remoteIds: [] });
      }
    });

    await AudioSession.startAudioSession();
    await lkRoom.connect(url, token);
    await lkRoom.localParticipant.setMicrophoneEnabled(true);

    // видео-звонок (этап 10): камера сразу; отказ — fallback «только звук»
    let camOn = false;
    if (current.kind === "video") {
      try {
        await lkRoom.localParticipant.setCameraEnabled(true);
        camOn = true;
      } catch {
        setErrorState("err_cam_denied");
      }
    }
    // аудио-звонок 1:1 — earpiece; видео/групповые — динамик (как в мессенджерах)
    const wantSpeaker = current.kind === "video";
    try {
      await AudioSession.selectAudioOutput(wantSpeaker ? "speaker" : "earpiece");
    } catch {
      // нет такого выхода (эмулятор) — системный дефолт
    }
    useCalls.setState({
      room: lkRoom,
      media: "connected",
      remoteIds: Array.from(lkRoom.remoteParticipants.keys()),
      camOn,
      speakerOn: wantSpeaker,
    });
  } catch {
    // сигналинг-звонок жив; медиа недоступно (LiveKit не запущен / нет UDP)
    useCalls.setState({ media: "idle" });
    setErrorState("err_media_unreachable");
  }
}
