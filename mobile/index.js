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

import { handlePushDeepLink, showMessageNotification } from "./src/services/push-service";
import { initTheme } from "./src/theme";

registerGlobals();

// Тема до первого рендера (§3.10): MMKV-настройка + listener system-режима
initTheme();

messaging().setBackgroundMessageHandler(async (remoteMessage) => {
  await showMessageNotification(remoteMessage);
});

void notifee.onBackgroundEvent(async ({ type, detail }) => {
  if (type === EventType.PRESS) {
    const chatId = detail.notification?.data?.chat_id;
    if (typeof chatId === "string") await handlePushDeepLink(chatId);
  }
});
