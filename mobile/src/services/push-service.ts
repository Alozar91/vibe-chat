/**
 * Push-сервис (Docs/android.md §3.5, этап 7): FCM-токен, регистрация на бэкенде,
 * показ уведомлений через notifee, deep link vibechat://chat/{id}.
 *
 * Дедуп с realtime (§3.5): foreground + живой WS → без уведомления (ленту
 * обновляет realtime-диспетчер). Background/quit → notifee рисует уведомление.
 * Тап → deep link в чат (холодный старт — сначала restore сессии, потом навигация).
 *
 * Payload пула содержит контент (решение 2026-11-25, §18): title/body от
 * бэкенда, lines для InboxStyle; chat_id — для дедупа и deep link.
 */

import { deleteApp, getApps, getApp, initializeApp } from "@react-native-firebase/app";
import messaging, { type FirebaseMessagingTypes } from "@react-native-firebase/messaging";
import { Platform } from "react-native";
import notifee, {
  AndroidImportance,
  AndroidStyle,
  AuthorizationStatus,
  EventType,
} from "@notifee/react-native";
import { api } from "./api-client";
import { config } from "./config";
import { useSession } from "../stores/session";
import { queryClient } from "./query-client";
import { queryKeys } from "../api/query-keys";
import type { Chat, ChatDetail } from "../api/types";

const CHANNEL_ID = "messages";
const SECONDARY_APP_NAME = "vibe-server";

/** Мессенджер активного Firebase-проекта (§19.6): наличие пушей определяет сервер,
 * а не сборка. FCM-токен — АДРЕС устройства, не учётка: отправить пуш по нему может
 * только держатель серверных кредов (SA-ключ) владеющего проекта; клиент креды
 * никогда не передаёт. Поэтому клиент консервативен:
 *  - driver != fcm → null (пуши выключены сервером);
 *  - сервер не назвал свой project_id (firebase=null) → null — токен официального
 *    проекта чужому серверу не выдаётся;
 *  - project_id совпал с зашитым (официальный проект) → дефолтный app;
 *  - другой project_id → secondary-app с конфигом СЕРВЕРА (initializeApp — промис
 *    в RN Firebase); токен принадлежит проекту сервера, слать может только он
 *    (его SA-ключ);
 *  - конфиг сервера битый/не инициализируется → null, НИКОГДА fallback на дефолт
 *    (иначе чужой сервер получил бы токен официального проекта).
 * Остаточный риск (осознанно принят, §19.6): сервер, скопировавший ПУБЛИЧНЫЙ
 * google-services.json официального проекта, может получить инертный токен
 * (отправить по нему нельзя без SA-ключа) — только кросс-серверная корреляция
 * устройства. */
/** Минимальная поверхность messaging, используемая push-сервисом. */
interface PushMessaging {
  getToken(): Promise<string>;
  deleteToken(): Promise<void>;
  onMessage(listener: (m: FirebaseMessagingTypes.RemoteMessage) => void): () => void;
  onTokenRefresh(listener: (token: string) => void): () => void;
  setBackgroundMessageHandler(
    handler: (m: FirebaseMessagingTypes.RemoteMessage) => Promise<void>,
  ): void;
}

/** Адаптер secondary-app (сервер со СВОИМ Firebase-проектом, §19.6).
 *
 * RNFB блокирует getMessaging(не-[DEFAULT]) на JS-уровне (hasMultiAppSupport:
 * false в реестре namespace — пропатчить нельзя, реестр не экспортируется),
 * но нативный слой per-app поддерживает: getToken/deleteToken принимают
 * override {appName, senderId} (namespaced.js → FirebaseApp.getInstance(appName)
 * .get(FirebaseMessaging.class)); события (onMessage/tokenRefresh/headless)
 * app-агностичны — сериализатор не кладёт appName в событие, подписка без
 * фильтра, поэтому слушатели дефолтного инстанса получают и чужие сообщения.
 * Токен-ротация вторичного app в onNewToken не различима (событие без appName)
 * — приемлемо: перерегистрация происходит при каждом логине/переподключении. */
class SecondaryMessaging implements PushMessaging {
  constructor(
    private base: FirebaseMessagingTypes.Module,
    private senderId: string,
  ) {}

  /** Токен ПРОЕКТА СЕРВЕРА (override appName), не дефолтного. */
  getToken(): Promise<string> {
    return this.base.getToken({ appName: SECONDARY_APP_NAME, senderId: this.senderId });
  }

  deleteToken(): Promise<void> {
    return this.base.deleteToken({ appName: SECONDARY_APP_NAME, senderId: this.senderId });
  }

  onMessage(listener: (m: FirebaseMessagingTypes.RemoteMessage) => void): () => void {
    return this.base.onMessage(listener);
  }

  onTokenRefresh(listener: (token: string) => void): () => void {
    return this.base.onTokenRefresh(listener);
  }

  setBackgroundMessageHandler(
    handler: (m: FirebaseMessagingTypes.RemoteMessage) => Promise<void>,
  ): void {
    this.base.setBackgroundMessageHandler(handler);
  }
}

async function activeMessaging(): Promise<PushMessaging | null> {
  const push = config.push;
  if (push.driver !== "fcm") return null;
  const fb = push.firebase;
  if (!fb?.project_id) {
    console.warn("[push] сервер объявил fcm без firebase-конфига — пуши отключены");
    return null;
  }
  try {
    const defaultOpts = getApps().length ? getApp().options : null;
    if (defaultOpts && defaultOpts.projectId === fb.project_id) {
      return messaging(); // тот же проект, что зашит — дефолтный app
    }
    let app = getApps().find((a) => a.name === SECONDARY_APP_NAME);
    if (!app) {
      try {
        app = await initializeApp(
          {
            projectId: fb.project_id,
            apiKey: fb.api_key,
            appId: fb.app_id,
            messagingSenderId: fb.sender_id,
            // модульный initializeApp валидирует опции ЖЁСТКО: databaseURL и
            // storageBucket обязательны (node_modules RNFB registry/app.js),
            // но в google-services.json databaseURL не бывает — синтезируем
            // канонический дефолт RTDB (не используется, только для валидации)
            databaseURL: `https://${fb.project_id}-default-rtdb.firebaseio.com`,
            storageBucket: fb.storage_bucket || `${fb.project_id}.appspot.com`,
          },
          SECONDARY_APP_NAME,
        );
      } catch (initError) {
        // гонка инициализации: если app создал параллельный вызов — переиспользуем;
        // если create реально упал — наружу (внешний catch отключит пуши)
        console.warn("[push] secondary initializeApp failed", initError);
        app = getApp(SECONDARY_APP_NAME);
      }
    }
    return new SecondaryMessaging(messaging(), fb.sender_id);
  } catch (e) {
    console.warn("[push] конфиг firebase сервера нерабочий — пуши отключены", e);
    return null;
  }
}

/** Смена сервера: secondary-app предыдущего сервера нужно убить, иначе повторный
 * initializeApp с тем же именем вернёт app со СТАРЫМИ опциями (§19.3). */
export async function resetSecondaryFirebaseApp(): Promise<void> {
  const existing = getApps().find((a) => a.name === SECONDARY_APP_NAME);
  if (existing) {
    await deleteApp(existing).catch(() => {});
  }
}

/** Текущий открытый чат — его уведомления не показываем и смываем. */
let activeChatId: string | null = null;

/** Вызывается из чат-экрана (focus/blur): открытый чат глушит свои пуши. */
export function setActiveChatId(chatId: string | null): void {
  activeChatId = chatId;
  if (chatId) void clearChatNotification(chatId);
}

// ── Разрешение POST_NOTIFICATIONS (§3.9: после логина, отказ не ломает) ────

/** true, если разрешение есть/получено. Отказ — false, приложение работает без пушей. */
export async function requestNotificationPermission(): Promise<boolean> {
  if (Platform.OS !== "android") return false;
  const status = (await notifee.requestPermission()).authorizationStatus;
  return status === AuthorizationStatus.AUTHORIZED || status === AuthorizationStatus.PROVISIONAL;
}

/** Системные настройки канала уведомлений (из профиля). */
export function openNotificationSettings(): void {
  if (Platform.OS !== "android") return;
  void notifee.openNotificationSettings();
}

/** Проверка без диалога (для настройки в профиле). */
export async function notificationsEnabled(): Promise<boolean> {
  if (Platform.OS !== "android") return false;
  const settings = await notifee.getNotificationSettings();
  const status = settings.authorizationStatus;
  return status === AuthorizationStatus.AUTHORIZED || status === AuthorizationStatus.PROVISIONAL;
}

// ── Канал уведомлений ──────────────────────────────────────────────────────

export async function ensureNotificationChannel(): Promise<void> {
  if (Platform.OS !== "android") return;
  await notifee.createChannel({
    id: CHANNEL_ID,
    name: "Сообщения",
    importance: AndroidImportance.HIGH,
  });
}

// ── Регистрация токена (POST /push/tokens, §3.8) ───────────────────────────

let registerInFlight: Promise<void> | null = null;

/** Регистрация FCM-токена текущего пользователя. Идемпотентна; ошибки — в лог. */
export async function registerPushToken(): Promise<void> {
  if (registerInFlight) return registerInFlight;
  registerInFlight = (async () => {
    try {
      if (Platform.OS !== "android") return;
      const m = await activeMessaging();
      if (!m) return; // сервер без пушей (§19.6) — регистрировать нечего
      const token = await m.getToken();
      await api("/push/tokens", { method: "POST", body: { token, platform: "android" } });
    } catch (e) {
      // не критично: повтор на следующем старте / tokenRefresh
      console.warn("[push] register failed", e);
    } finally {
      registerInFlight = null;
    }
  })();
  return registerInFlight;
}

/** Отвязка токена при выходе (DELETE /push/tokens/{token}, §3.8). */
export async function unregisterPushToken(): Promise<void> {
  if (Platform.OS !== "android") return;
  const m = await activeMessaging();
  if (!m) return;
  try {
    const token = await m.getToken();
    await api(`/push/tokens/${encodeURIComponent(token)}`, { method: "DELETE" });
    await m.deleteToken(); // FCM перегенерирует при следующем getToken
  } catch (e) {
    console.warn("[push] unregister failed", e);
  }
}

// ── Название чата из кэша (payload не содержит контента, §3.8) ─────────────

function chatTitle(chatId: string): string {
  const chats = queryClient.getQueryData<Chat[]>(queryKeys.chats.list());
  const chat = chats?.find((c) => c.id === chatId);
  if (chat?.title) return chat.title;
  // direct-чат: имя собеседника — в деталях чата (участники с user)
  const detail = queryClient.getQueryData<ChatDetail>(queryKeys.chats.detail(chatId));
  const me = useSession.getState().user;
  const other = detail?.members?.find((m) => m.user.id !== me?.id)?.user;
  return other?.display_name ?? "Vibe Chat";
}

// ── Показ уведомления (background/quit; foreground — глушим, §3.5) ─────────

/** Показ уведомления (background/quit; payload содержит контент — §3.8).
 *
 * title/body приходят готовыми от бэкенда («от кого и что», при склейке —
 * «N новых сообщений»); lines — до 5 последних сообщений для InboxStyle.
 */
export async function showMessageNotification(
  message: FirebaseMessagingTypes.RemoteMessage,
): Promise<void> {
  const chatId = asString(message.data?.chat_id);
  if (!chatId || chatId === activeChatId) return;
  const count = message.data?.count ? Number(message.data.count) : 1;
  const title = asString(message.data?.title) || chatTitle(chatId);
  const body = asString(message.data?.body) ?? (count > 1 ? `${count} новых сообщений` : "Новое сообщение");

  const android: {
    channelId: string;
    smallIcon: string;
    pressAction: { id: string };
    style?: { type: AndroidStyle.INBOX; lines: string[]; summary?: string };
  } = {
    channelId: CHANNEL_ID,
    smallIcon: "ic_launcher",
    pressAction: { id: "default" },
  };
  const linesRaw = asString(message.data?.lines);
  if (count > 1 && linesRaw) {
    try {
      const lines = JSON.parse(linesRaw) as unknown;
      if (Array.isArray(lines) && lines.length && lines.every((l) => typeof l === "string")) {
        android.style = { type: AndroidStyle.INBOX, lines, summary: body };
      }
    } catch {
      // битый JSON — показываем без раскладки
    }
  }

  await notifee.displayNotification({
    id: `chat-${chatId}`, // один notification на чат: повторный пуш обновляет
    title,
    body,
    data: { chat_id: chatId },
    android,
  });
}

// ── Deep link vibechat://chat/{id} (тап по уведомлению) ────────────────────

/** Навигация в чат после restore сессии (холодный старт, §3.6).
 * Дедуп 3 с: пресс-событие уведомления может прийти и в onBackgroundEvent,
 * и в onForegroundEvent (resumed activity) — двойной push чата недопустим. */
let lastDeepLink: { chatId: string; at: number } | null = null;

export async function handlePushDeepLink(chatId: string): Promise<void> {
  const now = Date.now();
  if (lastDeepLink && lastDeepLink.chatId === chatId && now - lastDeepLink.at < 3000) return;
  lastDeepLink = { chatId, at: now };
  console.info("[push] deep link to chat", chatId);
  const { router } = await import("expo-router");
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    if (useSession.getState().authenticated) {
      console.info("[push] navigating, authed");
      router.push(`/chats/${chatId}` as never);
      return;
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  console.warn("[push] deep link timeout: not authenticated");
}

/** data-payload FCM типизирован как string | object — у нас всегда строки. */
function asString(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

// ── Установка всех обработчиков (один раз из корневого layout) ─────────────

export async function installPushHandlers(): Promise<void> {
  if (Platform.OS !== "android") return;
  const m = await activeMessaging();
  if (!m) return; // сервер без пушей — обработчики FCM не нужны

  // foreground: ленту обновляет realtime-диспетчер (дедуп §3.5) — не рисуем.
  m.onMessage(() => {
    /* no-op: WS доставил */
  });

  // тап по уведомлению при живом приложении (foreground/background):
  // data-only FCM не имеет notification-части — тап отдаёт notifee.
  // Диспетчеризация — в call-notifications (сообщения и звонки §17 D);
  // динамический import — без статического цикла между сервисами.
  void notifee.onForegroundEvent(async ({ type, detail }) => {
    if (type !== EventType.PRESS) return;
    const { handleNotificationPress } = await import("./call-notifications");
    const data = (detail.notification?.data ?? {}) as Record<string, unknown>;
    await handleNotificationPress(detail.pressAction?.id, data);
  });

  // background/quit: Android будит JS — звонки → карты звонков (§17 D),
  // остальное — уведомления сообщений.
  m.setBackgroundMessageHandler(async (message) => {
    const data = (message.data ?? {}) as Record<string, unknown>;
    const type = typeof data.type === "string" ? data.type : "";
    if (type.startsWith("call.")) {
      const { handleCallDataPush } = await import("./call-notifications");
      await handleCallDataPush(data);
      return;
    }
    await showMessageNotification(message);
  });

  // старт приложения по тапу из уведомления (cold start): звонки (§17 D) —
  // ответ/отклонение/подъём оверлея из снапшота; сообщения — чат.
  void notifee
    .getInitialNotification()
    .then(async (initial) => {
      const data = (initial?.notification.data ?? {}) as Record<string, unknown>;
      const type = typeof data.type === "string" ? data.type : "";
      if (!type.startsWith("call.")) {
        const chatId = initial?.notification.data?.chat_id;
        if (typeof chatId === "string") return handlePushDeepLink(chatId);
        return;
      }
      const { handleNotificationPress } = await import("./call-notifications");
      await handleNotificationPress(initial?.pressAction?.id, data);
    })
    .catch(() => {});

  // ротация токена на стороне FCM → перерегистрация (§3.8)
  m.onTokenRefresh(() => {
    if (useSession.getState().authenticated) void registerPushToken();
  });
}

/** Уведомления чата смыть (открыл чат — всё прочитано). */
export async function clearChatNotification(chatId: string): Promise<void> {
  await notifee.cancelDisplayedNotification(`chat-${chatId}`);
}
