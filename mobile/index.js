/**
 * Точка входа Expo Router. Сюда — только то, что обязано выполниться до
 * рендера корневого layout'а: headless-обработчики FCM/notifee (background/quit,
 * Docs/android.md §3.5). Регистрация на top-level, до AppRegistry — иначе
 * Android будит процесс без зарегистрированной задачи
 * ("No task registered for key ReactNativeFirebaseMessagingHeadlessTask")
 * и уведомление не рисуется.
 *
 * notifee.onBackgroundEvent — тап по уведомлению (press) при убитом/фоновом
 * приложении: data-only FCM не несёт notification-части, поэтому тап-событие
 * отдаёт notifee, а не RN Firebase.
 */
import "expo-router/entry";
import messaging from "@react-native-firebase/messaging";
import notifee, { EventType } from "@notifee/react-native";
// LiveKit RN (§3.12): глобалы WebRTC (navigator.mediaDevices и др.) —
// обязателен до загрузки любого кода, использующего livekit-client
import { registerGlobals } from "@livekit/react-native";

import { showMessageNotification } from "./src/services/push-service";
import {
  handleCallDataPush,
  handleNotificationPress,
  registerCallForegroundService,
} from "./src/services/call-notifications";
import { initTheme } from "./src/theme";

registerGlobals();

// Тема до первого рендера (§3.10): MMKV-настройка + listener system-режима
initTheme();

// Фоновые звонки (§17 D): runner foreground service — ДО первого показа
// asForegroundService-уведомления (карта входящего звонка держит процесс
// и ринг-луп; в каждом JS-контексте — своя регистрация, это норма)
registerCallForegroundService();

// GMS-less устройства (без Google Play Services): FirebaseApp инициализируется,
// но FCM-операции недоступны — получить токен нельзя, пуши не приходят (§19.6).
// Ошибка здесь недопустима: это top-level до AppRegistry — уронит холодный старт
// всего приложения. Ловим и живём без пушей (проверка: AVD без Google APIs).
try {
  messaging().setBackgroundMessageHandler(async (remoteMessage) => {
    // звонки (§17 D): call.* → карты звонков/снятие; остальное — сообщения
    const data = (remoteMessage.data ?? {});
    const type = typeof data.type === "string" ? data.type : "";
    if (type.startsWith("call.")) {
      await handleCallDataPush(data);
      return;
    }
    await showMessageNotification(remoteMessage);
  });
} catch (e) {
  console.warn("[push] headless FCM недоступен (нет Google Play Services?)", e);
}

void notifee.onBackgroundEvent(async ({ type, detail }) => {
  if (type !== EventType.PRESS) return;
  // Диспетчеризация: сообщения → чат, звонки (§17 D) → answer/decline/оверлей.
  // В headless VM dispatch ограничен REST (AppState 'unknown'); UI-путь поднимает
  // контекст приложения (getInitialNotification в push-service)
  const data = (detail.notification?.data ?? {});
  await handleNotificationPress(detail.pressAction?.id, data);
});
