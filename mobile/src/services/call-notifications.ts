/**
 * Уведомления звонков (§17 D, этап 11): фоновые входящие звонки при убитом
 * или свёрнутом приложении. Сигналинг звонка живёт в WS, который при убитом
 * процессе не доставится — ринг дублируется FCM data-пушем call.ring
 * (бэкенд: backend/app/services/push.py, правила аудитории §18).
 *
 * Сборка «входящего звонка» без CallStyle (notifee 9.x его не имеет):
 * AndroidCategory.CALL + fullScreenAction (полноэкранный интент на экране
 * блокировки) + действия Ответить/Отклонить + foreground service
 * (asForegroundService: держит процесс и карту, пока идёт ринг; звук —
 * луп ringPlayer из сервиса).
 *
 * ВАЖНО (§3.5): headless-контекст FCM и контекст приложения — разные JS VM
 * с разными zustand-сторами. Поэтому пресс-события уведомлений диспетчеризуются
 * так: REST-мутации (accept/reject) — напрямую через callsApi, 409-толерантно
 * (принять мог параллельный контекст); стор/оверлей/медиа поднимает только
 * контекст приложения (cold start — getInitialNotification, живой — стор уже
 * с звонком от WS). Циклы импортов разрываем динамическими import().
 */

import notifee, { AndroidCategory, AndroidImportance, type Notification } from "@notifee/react-native";
import { Platform } from "react-native";
import { callsApi } from "../api/endpoints";
import { ringPlayer } from "./ring";

export const CALL_CHANNEL_ID = "calls";

/** TTL карты входящего звонка = TTL ринга на бэкенде (§17, 45 c). */
const RING_TTL_MS = 45_000;

/** Данные карты звонка (из FCM data-пуша или из WS Call для локального показа). */
export interface CallNotificationPayload {
  call_id: string;
  chat_id: string;
  caller_id: string;
  caller_name: string;
  kind: "audio" | "video";
}

// ── Канал «Звонки» ─────────────────────────────────────────────────────────

export async function ensureCallChannel(): Promise<void> {
  if (Platform.OS !== "android") return;
  await notifee.createChannel({
    id: CALL_CHANNEL_ID,
    name: "Звонки",
    importance: AndroidImportance.HIGH,
    // мгновенный алерт до старта headless-лупа (файл android/app/src/main/res/raw/ring.wav)
    sound: "ring",
    vibration: true,
    vibrationPattern: [500, 800, 500, 800, 500, 1500],
  });
}

// ── Показ карт звонков ─────────────────────────────────────────────────────

/** Входящий direct-звонок: карта с Ответить/Отклонить + full-screen intent. */
export async function showIncomingCallNotification(p: CallNotificationPayload): Promise<void> {
  await ensureCallChannel();
  const title = p.kind === "video" ? "Входящий видеозвонок" : "Входящий звонок";
  await notifee.displayNotification({
    id: `call-${p.call_id}`, // один id на звонок: повторный ринг перезаписывает карту
    title,
    body: p.caller_name,
    data: { type: "call.ring", call_id: p.call_id, chat_id: p.chat_id, caller_id: p.caller_id, caller_name: p.caller_name, kind: p.kind },
    android: {
      channelId: CALL_CHANNEL_ID,
      category: AndroidCategory.CALL,
      smallIcon: "ic_launcher",
      ongoing: true,
      importance: AndroidImportance.HIGH,
      fullScreenAction: { id: "default", launchActivity: "default" },
      pressAction: { id: "default", launchActivity: "default" },
      actions: [
        { title: "Ответить", pressAction: { id: "answer", launchActivity: "default" } },
        { title: "Отклонить", pressAction: { id: "decline" } },
      ],
      asForegroundService: true, // держит процесс и карту до accept/reject/TTL (§17 D)
    },
  });
}

/** Групповой звонок начался: обычная карта, тап → чат (баннер join внутри). */
export async function showGroupCallNotification(p: CallNotificationPayload): Promise<void> {
  // канал messages создаётся при логине (push-service); в headless его может
  // не быть — createChannel идемпотентен, страховка бесплатна
  await notifee.createChannel({ id: "messages", name: "Сообщения", importance: AndroidImportance.HIGH });
  await notifee.displayNotification({
    id: `call-${p.call_id}`,
    title: p.kind === "video" ? "Групповой видеозвонок" : "Групповой звонок",
    body: p.caller_name,
    data: { type: "call.started", call_id: p.call_id, chat_id: p.chat_id },
    android: {
      // канал messages (звук по умолчанию): ринг-звук канала «Звонки» тут неуместен
      channelId: "messages",
      smallIcon: "ic_launcher",
      pressAction: { id: "default", launchActivity: "default" },
      importance: AndroidImportance.HIGH,
    },
  });
}

// ── Foreground service (ринг-луп, пока карта висит) ────────────────────────

interface RunningService {
  timer: ReturnType<typeof setTimeout>;
  finish: () => void;
}
const runningServices = new Map<string, RunningService>();

function stopRingLoop(): void {
  ringPlayer.stop();
}

/** Регистрация runner'а foreground service — один раз на JS-контекст,
 * до первого показа asForegroundService-уведомления (из index.js). */
export function registerCallForegroundService(): void {
  if (Platform.OS !== "android") return;
  try {
    notifee.registerForegroundService(async (notification: Notification) => {
      const data = notification.data ?? {};
      const callId = typeof data.call_id === "string" ? data.call_id : null;
      if (data.type !== "call.ring" || !callId) return; // не ринг — не держим сервис
      // звук: луп через expo-audio (канал дал только мгновенный алерт).
      // В headless-контексте может не завестись — тогда остаётся звук канала.
      void ringPlayer.start().catch(() => {});
      await new Promise<void>((resolve) => {
        const timer = setTimeout(() => {
          runningServices.delete(callId);
          // страховка TTL: карта не должна висеть дольше ринга бэкенда
          void cancelCallNotification(callId);
        }, RING_TTL_MS);
        runningServices.set(callId, { timer, finish: resolve });
      });
      stopRingLoop();
    });
  } catch (e) {
    console.warn("[call-notifications] registerForegroundService failed", e);
  }
}

/** Снять карту звонка (и остановить сервис/ринг). Идемпотентно. */
export async function cancelCallNotification(callId: string): Promise<void> {
  stopRingLoop();
  const running = runningServices.get(callId);
  if (running) {
    clearTimeout(running.timer);
    runningServices.delete(callId);
    running.finish();
  }
  await notifee.cancelDisplayedNotification(`call-${callId}`).catch(() => {});
  await notifee.stopForegroundService().catch(() => {});
}

// ── REST-мутации из пресс-событий (без стора — §3.5) ───────────────────────

/** Принять звонок из уведомления. 409 = уже принят (другой контекст/устройство) —
 * не ошибка. Ошибки глотаются: карта всё равно снимается. */
export async function acceptCallRest(callId: string): Promise<void> {
  try {
    await callsApi.accept(callId);
  } catch (e) {
    console.info("[call-notifications] accept (или уже принят)", e);
  }
}

/** Отклонить из уведомления; карта снимается в любом случае. */
export async function declineCallRest(callId: string): Promise<void> {
  try {
    await callsApi.reject(callId);
  } catch (e) {
    console.info("[call-notifications] reject (или уже завершён)", e);
  }
  void cancelCallNotification(callId);
}

// ── Диспетчер пресс-событий ────────────────────────────────────────────────

/** Обработка пресc-события уведомления (foreground/background/initial).
 * pressActionId — detail.pressAction?.id (у initial — initial.pressAction?.id). */
export async function handleNotificationPress(
  pressActionId: string | undefined,
  data: Record<string, unknown>,
): Promise<void> {
  const type = typeof data.type === "string" ? data.type : undefined;
  const callId = typeof data.call_id === "string" ? data.call_id : undefined;
  const chatId = typeof data.chat_id === "string" ? data.chat_id : undefined;

  if (type === "call.started" && chatId) {
    const { handlePushDeepLink } = await import("./push-service");
    await handlePushDeepLink(chatId);
    return;
  }

  if (type === "call.ring" && callId) {
    if (pressActionId === "decline") {
      await declineCallRest(callId);
      return;
    }
    if (pressActionId === "answer") {
      // REST первым делом (быстрее, чем загрузится UI; идемпотентно: 409 = уже
      // принял другой контекст/устройство)
      await acceptCallRest(callId);
      // карта больше не нужна в любом исходе accept (в т.ч. 409) — иначе висит до TTL
      await cancelCallNotification(callId);
      // UI-путь (стор + оверлей + медиа) — только в контексте приложения:
      // в headless VM стор «пустышка», connectMedia там не нужен и вреден.
      // Признак headless-контекста — AppState 'unknown' (в живом приложении
      // 'active'/'background'; в холодном headless активити нет).
      const { AppState } = await import("react-native");
      if (AppState.currentState === "unknown") return;
      const { useCalls } = await import("../stores/calls");
      await useCalls.getState().acceptFromNotification(callId, snapshotFromData(data));
      return;
    }
    // тап по телу карты — поднять оверлей звонка (контекст приложения):
    // cold start — стор пуст → снапшот станет current (оверлей ринга);
    // живой процесс — WS уже поставил current → adoptIncomingCall no-op
    const { AppState } = await import("react-native");
    if (AppState.currentState !== "unknown") {
      const { useCalls } = await import("../stores/calls");
      useCalls.getState().adoptIncomingCall(callId, snapshotFromData(data));
      return;
    }
    // headless VM: не наш контекст — пусть откроется чат (initial-ветка
    // контекста приложения поднимет оверлей из того же снапшота)
    if (chatId) {
      const { handlePushDeepLink } = await import("./push-service");
      await handlePushDeepLink(chatId);
    }
    return;
  }

  // дефолт — уведомления сообщений: тап → чат
  if (chatId) {
    const { handlePushDeepLink } = await import("./push-service");
    await handlePushDeepLink(chatId);
  }
}

function snapshotFromData(data: Record<string, unknown>): CallNotificationPayload {
  return {
    call_id: String(data.call_id ?? ""),
    chat_id: String(data.chat_id ?? ""),
    caller_id: String(data.caller_id ?? ""),
    caller_name: typeof data.caller_name === "string" ? data.caller_name : "",
    kind: data.kind === "video" ? "video" : "audio",
  };
}

/** Data-пуш звонка из FCM (background/quit): call.ring → карта входящего,
 * call.started → карта группы, call.cancelled → снять карту.
 * Вызывается из setBackgroundMessageHandler (index.js и push-service) —
 * без этого пуш звонка рисовался бы как «новое сообщение» (chat_id есть в
 * payload). В foreground FCM-пушей звонков не бывает (presence-фильтр бэкенда). */
export async function handleCallDataPush(data: Record<string, unknown>): Promise<void> {
  const type = typeof data.type === "string" ? data.type : "";
  const callId = typeof data.call_id === "string" ? data.call_id : "";
  if (!callId) return;
  if (type === "call.cancelled") {
    await cancelCallNotification(callId);
    return;
  }
  if (type === "call.ring") {
    await showIncomingCallNotification(snapshotFromData(data));
    return;
  }
  if (type === "call.started") {
    await showGroupCallNotification(snapshotFromData(data));
  }
}
