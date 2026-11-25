/**
 * Стор звонков (§3.12): порт вебового frontend/src/realtime/calls.ts.
 * Сигналинг — WS-события call.* (источник истины по статусу, §17);
 * мутации — REST; медиа — прямое подключение к LiveKit по room-токену.
 * Zustand вне TanStack Query — звонок не кэш, а живое состояние.
 */

import { AudioSession } from "@livekit/react-native";
import { create } from "zustand";
import { Room, RoomEvent, Track, type VideoTrack } from "livekit-client";
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
  /** Активная камера: user = фронтальная (зеркалится), environment = основная. */
  facing: "user" | "environment";
  /** Живые (subscribed+unmuted) камеры удалённых участников по identity. */
  remoteCams: Record<string, VideoTrack | null>;
  /** Мой локальный видео-трек (для PiP/своей плитки); null = камера выключена. */
  localCam: VideoTrack | null;
  /** Громкая связь; default — earpiece у аудио-звонков. */
  speakerOn: boolean;
  error: string | null;

  handleWsEvent: (type: string, data: unknown) => void;
  start: (chatId: string, kind?: "audio" | "video") => Promise<void>;
  join: (callId: string) => Promise<void>;
  accept: (withVideo?: boolean) => Promise<void>;
  reject: () => Promise<void>;
  cancel: () => Promise<void>;
  leave: () => Promise<void>;
  toggleMute: () => Promise<void>;
  toggleCam: () => Promise<void>;
  /** Переключение фронтальная/основная камера (этап 10). */
  switchCam: () => Promise<void>;
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
  facing: "user",
  remoteCams: {},
  localCam: null,
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
        // эхо ринга своего звонка: не откатываем уже активный звонок в ringing
        if (st.current.status !== "active") {
          set({ current: call });
          syncRing();
        }
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
      if (kind === "video" && !(await ensureCamPermission())) setErrorState("err_cam_denied");
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
      if (call.kind === "video" && !(await ensureCamPermission())) setErrorState("err_cam_denied");
      await connectMedia();
    } catch (err) {
      setErrorState(errMessage(err));
    }
  },

  accept: async (withVideo = true) => {
    const call = get().current;
    if (!call) return;
    setErrorState(null);
    try {
      await ensureMicPermission();
      // «ответить без видео» — камера не запрашивается и не публикуется
      if (call.kind === "video" && withVideo && !(await ensureCamPermission())) setErrorState("err_cam_denied");
      const updated = await callsApi.accept(call.id);
      set({ current: updated });
      syncRing();
      await connectMedia(withVideo);
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
    try {
      if (next) {
        // включение камеры требует разрешения (после «ответа без видео» его ещё нет)
        if (!(await ensureCamPermission())) {
          setErrorState("err_cam_denied");
          return;
        }
        // RN-специфика (этап 10): mute глушит капчер и unmute его не возрождает
        // (сервер навсегда видит muted) — камеру включаем пересозданием трека
        const lp = room.localParticipant;
        const pub = lp.getTrackPublication(Track.Source.Camera);
        if (pub?.track) {
          try {
            lp.unpublishTrack(pub.track);
          } catch {
            // трек уже мёртв — не критично
          }
        }
        // сохраняем выбранную камеру (facing) при пересоздании трека
        await lp.setCameraEnabled(true, get().facing === "user" ? undefined : { facingMode: "environment" });
      } else {
        await room.localParticipant.setCameraEnabled(false);
      }
      set({ camOn: next });
    } catch {
      setErrorState("err_cam_denied");
    }
  },

  /** Смена фронтальная/основная: applyConstraints(facingMode) на живом треке
   * (RN-webrtc сам переключает капчер без renegotiation); трек и sid те же,
   * поэтому remoteCams/localCam не меняются — меняется только зеркалирование. */
  switchCam: async () => {
    const room = get().room;
    if (!room || !get().camOn) return; // камера выключена — переключать нечего
    const pub = room.localParticipant.getTrackPublication(Track.Source.Camera);
    const mt = (pub?.videoTrack?.mediaStreamTrack ?? null) as {
      applyConstraints?: (c: unknown) => Promise<void>;
    } | null;
    if (!mt?.applyConstraints) return;
    const next = get().facing === "user" ? "environment" : "user";
    try {
      await mt.applyConstraints({ facingMode: next });
      set({ facing: next });
    } catch {
      // второй камеры нет (или все заняты) — сообщаем и не трогаем состояние
      setErrorState("err_cam_switch");
    }
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
      facing: "user",
      remoteCams: {},
      localCam: null,
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

/** CAMERA для видеозвонков; отказ — не прерывает звонок (fallback «только звук»). */
async function ensureCamPermission(): Promise<boolean> {
  if (Platform.OS !== "android") return true;
  const perm = PermissionsAndroid.PERMISSIONS.CAMERA as Permission;
  const has = await PermissionsAndroid.check(perm);
  if (has) return true;
  const res = await PermissionsAndroid.request(perm, {
    title: "Камера",
    message: "Vibe Chat нужен доступ к камере для видеозвонков",
    buttonPositive: "OK",
  });
  return res === PermissionsAndroid.RESULTS.GRANTED;
}

// --- LiveKit-подключение (медиа, §17) ---

async function connectMedia(withVideo = true): Promise<void> {
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
    // камеры (этап 10): live = subscribed и не замьючена; остальное — заглушка с аватаром
    const syncCams = () => {
      if (!isCurrent()) return;
      const cams: Record<string, VideoTrack | null> = {};
      lkRoom.remoteParticipants.forEach((p) => {
        const pub = p.getTrackPublication(Track.Source.Camera);
        const v = pub?.videoTrack;
        cams[p.identity] = pub?.isSubscribed && v && !pub.isMuted ? v : null;
      });
      useCalls.setState({ remoteCams: cams });
    };
    const syncLocalCam = () => {
      if (!isCurrent()) return;
      const pub = lkRoom.localParticipant.getTrackPublication(Track.Source.Camera);
      // toggleCam мьютит трек (не анпаблишит) — замьюченная камера = PiP скрыт
      useCalls.setState({ localCam: pub && !pub.isMuted ? pub.videoTrack ?? null : null });
    };
    lkRoom.on(RoomEvent.ParticipantConnected, syncRemote);
    lkRoom.on(RoomEvent.ParticipantDisconnected, syncRemote);
    for (const ev of [
      RoomEvent.TrackSubscribed,
      RoomEvent.TrackUnsubscribed,
      RoomEvent.TrackPublished,
      RoomEvent.TrackUnpublished,
      RoomEvent.TrackMuted,
      RoomEvent.TrackUnmuted,
    ]) {
      lkRoom.on(ev, syncCams);
    }
    lkRoom.on(RoomEvent.LocalTrackPublished, syncLocalCam);
    lkRoom.on(RoomEvent.LocalTrackUnpublished, syncLocalCam);
    lkRoom.on(RoomEvent.TrackMuted, syncLocalCam);
    lkRoom.on(RoomEvent.TrackUnmuted, syncLocalCam);
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

    // видео-звонок (этап 10): камера сразу; отказ — fallback «только звук»;
    // ответ без видео — камера не включается (можно включить кнопкой)
    let camOn = false;
    let localCam: VideoTrack | null = null;
    if (current.kind === "video" && withVideo) {
      try {
        await lkRoom.localParticipant.setCameraEnabled(true);
        camOn = true;
        localCam = lkRoom.localParticipant.getTrackPublication(Track.Source.Camera)?.videoTrack ?? null;
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
      remoteCams: {},
      localCam,
      camOn,
      speakerOn: wantSpeaker,
    });
    syncCams();
  } catch {
    // сигналинг-звонок жив; медиа недоступно (LiveKit не запущен / нет UDP)
    useCalls.setState({ media: "idle" });
    setErrorState("err_media_unreachable");
  }
}
