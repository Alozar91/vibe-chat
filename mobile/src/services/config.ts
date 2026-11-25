/**
 * Конфигурация приложения (Docs/android.md §3.13, концепция §19): единственная
 * точка доступа к параметрам окружения. Источник — профиль сервера (MMKV,
 * `server-profile.ts`), полученный из GET /server/info при онбординге. Статических
 * `EXPO_PUBLIC_*` больше нет, кроме dev-override'а LiveKit (§3.12).
 *
 * Все адреса выводятся из адреса сервера: REST `{base}/api/v1`, WS `{base}/api/v1/ws`
 * (схема ws/wss по протоколу), Keycloak — из профиля (kc_url + realm). Client id
 * мобильного — константа продукта (`mobile`, §19.2 концепции).
 *
 * Геттеры бросают, если профиль не выбран, — все потребители должны жить ПОСЛЕ
 * онбординга (роутинг это гарантирует: без профиля рендерится только connect).
 */

import { wsSchemeFor, useServerProfile } from "./server-profile";

function requireProfile() {
  const profile = useServerProfile.getState().profile;
  if (!profile) {
    throw new Error("Сервер не выбран: конфиг доступен только после онбординга");
  }
  return profile;
}

/** dev-only override LiveKit (§3.12): в dev ws://10.0.2.2:7880, из эмулятора
 * localhost не резолвится. На стенде/в self-host не задаётся — ws_url из room-токена. */
const livekitOverride =
  process.env.EXPO_PUBLIC_LIVEKIT_URL && process.env.EXPO_PUBLIC_LIVEKIT_URL.length > 0
    ? process.env.EXPO_PUBLIC_LIVEKIT_URL
    : null;

export const config = {
  /** REST base: {адрес сервера}/api/v1 */
  get apiBase(): string {
    return `${requireProfile().baseUrl}/api/v1`;
  },

  /** WS base: та же точка монтирования, схема ws/wss по протоколу адреса */
  get wsBase(): string {
    const p = requireProfile();
    return `${wsSchemeFor(p.baseUrl)}${p.baseUrl.replace(/^https?:\/\//i, "")}/api/v1/ws`;
  },

  get kcUrl(): string {
    return requireProfile().kcUrl;
  },

  get kcRealm(): string {
    return requireProfile().realm;
  },

  /** client id мобильного клиента — константа продукта (§19.2) */
  kcClientId: "mobile",

  /** Кодовое слово сервера (заголовок X-Vibe-Join); пусто = не задан (§19.5) */
  get joinCode(): string | null {
    const code = requireProfile().joinCode;
    return code ? code : null;
  },

  /** Пуш-конфигурация сервера (§19.6): наличие пушей определяет сервер, не сборка */
  get push() {
    return requireProfile().push;
  },

  /** Ссылка на раздачу APK этого сервера (§3.8/§19.4); не задана — null */
  get appDownloadUrl(): string | null {
    return requireProfile().appDownloadUrl || null;
  },

  /** LiveKit WS для звонков: dev-override или ws_url из room-токена (§3.12) */
  livekitUrl: livekitOverride,

  /** OAuth endpoints Keycloak (ROPC — token, PKCE fallback — authorize) */
  get kc() {
    const base = `${this.kcUrl}/realms/${this.kcRealm}`;
    return {
      tokenEndpoint: `${base}/protocol/openid-connect/token`,
      authorizeEndpoint: `${base}/protocol/openid-connect/auth`,
      logoutEndpoint: `${base}/protocol/openid-connect/logout`,
      revocationEndpoint: `${base}/protocol/openid-connect/revoke`,
    };
  },
};
