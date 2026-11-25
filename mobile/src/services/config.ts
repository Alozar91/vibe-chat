/**
 * Конфигурация приложения — единственная точка чтения env (Docs/android.md §3.7).
 * Всё через EXPO_PUBLIC_* (запекаются при сборке); без хардкода в рантайме.
 */

function required(name: string): string {
  const value = process.env[`EXPO_PUBLIC_${name}`];
  if (!value) {
    throw new Error(
      `EXPO_PUBLIC_${name} не задан. Скопируйте mobile/.env.example в mobile/.env и заполните.`
    );
  }
  return value;
}

export const config = {
  apiBase: required("API_BASE"),
  wsBase: required("WS_BASE"),
  siloPublicUrl: required("SILO_PUBLIC_URL"),
  kcUrl: required("KC_URL"),
  kcRealm: required("KC_REALM"),
  kcClientId: required("KC_CLIENT_ID"),

  /** LiveKit WS для звонков (§3.12): бэкенд возвращает ws_url в room-токене;
   * в dev (ws://localhost:7880) из эмулятора не резолвится — override на
   * ws://10.0.2.2:7880. На стенде не задан — ws_url (wss://…/chat/livekit) верен.
   */
  livekitUrl: process.env.EXPO_PUBLIC_LIVEKIT_URL || null,

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
