import { devicesApi } from "../../api/endpoints";
import { useToastStore } from "../../stores/ui";

export function isWebPushSupported(): boolean {
  return typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export function pushStatus(): "unsupported" | "denied" | "granted" | "default" {
  if (!isWebPushSupported()) return "unsupported";
  return Notification.permission as "denied" | "granted" | "default";
}

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const normalized = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(normalized);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) {
    output[i] = raw.charCodeAt(i);
  }
  return output;
}

export async function enableWebPush(): Promise<{ ok: boolean; reason?: string }> {
  if (!isWebPushSupported()) return { ok: false, reason: "Браузер не поддерживает Web Push" };
  const vapidKey = import.meta.env.VITE_VAPID_PUBLIC_KEY as string | undefined;
  if (!vapidKey) return { ok: false, reason: "VAPID-ключ не настроен (VITE_VAPID_PUBLIC_KEY)" };
  try {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") return { ok: false, reason: "Разрешение не выдано" };
    const registration = await navigator.serviceWorker.register("/service-worker.js");
    await navigator.serviceWorker.ready;
    const existing = await registration.pushManager.getSubscription();
    const subscription =
      existing ||
      (await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapidKey) as BufferSource,
      }));
    await devicesApi.register({ platform: "web", webpush_subscription: subscription.toJSON() as Record<string, unknown> });
    useToastStore.getState().push({ kind: "success", title: "Push-уведомления включены" });
    return { ok: true };
  } catch (error) {
    return { ok: false, reason: error instanceof Error ? error.message : "Ошибка подписки" };
  }
}
