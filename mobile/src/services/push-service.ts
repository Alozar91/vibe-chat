/**
 * Push-сервис (Docs/android.md §3.5, этап 7): FCM-токен, регистрация на бэкенде,
 * показ уведомлений через notifee, deep link vibechat://chat/{id}.
 *
 * Дедуп с realtime (§3.5): foreground + живой WS → без уведомления (ленту
 * обновляет realtime-диспетчер). Background/quit → notifee рисует уведомление.
 * Тап → deep link в чат (холодный старт — сначала restore сессии, потом навигация).
 *
 * Payload пула — только идентификаторы (chat_id, message_id, count, §3.8):
 * текст не светим в FCM-шине; в уведомлении — название чата из кэша + count.
 */

import messaging, {
  type FirebaseMessagingTypes,
} from "@react-native-firebase/messaging";
import { Platform } from "react-native";
import notifee, {
  AndroidImportance,
  AuthorizationStatus,
  EventType,
} from "@notifee/react-native";
import { api } from "./api-client";
import { useSession } from "../stores/session";
import { queryClient } from "./query-client";
import { queryKeys } from "../api/query-keys";
import type { Chat, ChatDetail } from "../api/types";

const CHANNEL_ID = "messages";

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
      const token = await messaging().getToken();
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
  try {
    const token = await messaging().getToken();
    await api(`/push/tokens/${encodeURIComponent(token)}`, { method: "DELETE" });
    await messaging().deleteToken(); // FCM перегенерирует при следующем getToken
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

export async function showMessageNotification(
  message: FirebaseMessagingTypes.RemoteMessage,
): Promise<void> {
  const chatId = asString(message.data?.chat_id);
  if (!chatId || chatId === activeChatId) return;
  const count = message.data?.count ? Number(message.data.count) : 1;
  const title = chatTitle(chatId);
  const body = count > 1 ? `${count} новых сообщения` : "Новое сообщение";
  await notifee.displayNotification({
    id: `chat-${chatId}`, // один notification на чат: повторный пуш обновляет
    title,
    body,
    data: { chat_id: chatId },
    android: {
      channelId: CHANNEL_ID,
      smallIcon: "ic_launcher",
      pressAction: { id: "default" },
    },
  });
}

// ── Deep link vibechat://chat/{id} (тап по уведомлению) ────────────────────

/** Навигация в чат после restore сессии (холодный старт, §3.6). */
export async function handlePushDeepLink(chatId: string): Promise<void> {
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

export function installPushHandlers(): void {
  if (Platform.OS !== "android") return;

  // foreground: ленту обновляет realtime-диспетчер (дедуп §3.5) — не рисуем.
  messaging().onMessage(() => {
    /* no-op: WS доставил */
  });

  // тап по уведомлению при живом приложении (foreground/background):
  // data-only FCM не имеет notification-части — тап отдаёт notifee.
  void notifee.onForegroundEvent(async ({ type, detail }) => {
    if (type === EventType.PRESS) {
      const chatId = detail.notification?.data?.chat_id;
      if (typeof chatId === "string") await handlePushDeepLink(chatId);
    }
  });

  // background/quit: Android будит JS — рисуем уведомление.
  messaging().setBackgroundMessageHandler(async (message) => {
    await showMessageNotification(message);
  });

  // тап при живом (background) приложении: data-only FCM не имеет notification-
  // части — открытие и тап отдаёт notifee (RN Firebase тут не участвует).
  void notifee
    .getInitialNotification()
    .then((initial) => {
      const chatId = initial?.notification.data?.chat_id;
      if (typeof chatId === "string") return handlePushDeepLink(chatId);
    })
    .catch(() => {});

  // ротация токена на стороне FCM → перерегистрация (§3.8)
  messaging().onTokenRefresh(() => {
    if (useSession.getState().authenticated) void registerPushToken();
  });
}

/** Уведомления чата смыть (открыл чат — всё прочитано). */
export async function clearChatNotification(chatId: string): Promise<void> {
  await notifee.cancelDisplayedNotification(`chat-${chatId}`);
}
