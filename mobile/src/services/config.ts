/**
 * Конфигурация приложения — единственная точка чтения env (Docs/android.md §3.7).
 * Всё через EXPO_PUBLIC_* (запекаются при сборке); без хардкода в рантайме.
 *
 * ВАЖНО: доступ к process.env — ТОЛЬКО статический (`process.env.EXPO_PUBLIC_X`).
 * babel-инлайнер Expo подставляет значения только для литеральных обращений —
 * динамический `process.env['EXPO_PUBLIC_' + name]` в release-бандле = undefined
 * (в debug его выручает рантайм-гидратация env от dev-сервера, в release её нет).
 */

function required(value: string | undefined, name: string): string {
  if (!value) {
    throw new Error(
      `EXPO_PUBLIC_${name} не задан. Скопируйте mobile/.env.example в mobile/.env и заполните.`
    );
  }
  return value;
}

export const config = {
  apiBase: required(process.env.EXPO_PUBLIC_API_BASE, "API_BASE"),
  wsBase: required(process.env.EXPO_PUBLIC_WS_BASE, "WS_BASE"),
  siloPublicUrl: required(process.env.EXPO_PUBLIC_SILO_PUBLIC_URL, "SILO_PUBLIC_URL"),
  kcUrl: required(process.env.EXPO_PUBLIC_KC_URL, "KC_URL"),
  kcRealm: required(process.env.EXPO_PUBLIC_KC_REALM, "KC_REALM"),
  kcClientId: required(process.env.EXPO_PUBLIC_KC_CLIENT_ID, "KC_CLIENT_ID"),

  /** LiveKit WS для звонков (§3.12): бэкенд возвращает ws_url в room-токене;
   * в dev (ws://localhost:7880) из эмулятора не резолвится — override на
   * ws://10.0.2.2:7880. На стенде не задан — ws_url (wss://…/chat/livekit) верен.
   */
  livekitUrl: process.env.EXPO_PUBLIC_LIVEKIT_URL || null,

  /** Прямая ссылка на раздачу APK (§3.8): показывается на блокирующем
   * экране устаревшей версии. Не задана — текст «обратитесь к администратору». */
  appDownloadUrl: process.env.EXPO_PUBLIC_APP_DOWNLOAD_URL || null,

  /** OAuth endpoints Keycloak (ROPC — token endpoint, PKCE fallback — authorize) */
  get kc() {
    return {
      tokenEndpoint: `${this.kcUrl}/realms/${this.kcRealm}/protocol/openid-connect/token`,
      authorizeEndpoint: `${this.kcUrl}/realms/${this.kcRealm}/protocol/openid-connect/auth`,
      logoutEndpoint: `${this.kcUrl}/realms/${this.kcRealm}/protocol/openid-connect/logout`,
      revocationEndpoint: `${this.kcUrl}/realms/${this.kcRealm}/protocol/openid-connect/revoke`,
    };
  },
} as const;

export type AppConfig = typeof config;
