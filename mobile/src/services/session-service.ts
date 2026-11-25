/**
 * Session orchestration (Docs/android.md §3.2): login/restore/logout как
 * сервис, не UI. UI только вызывает и рендерит результат.
 *
 * Жизненный цикл:
 *   холодный старт: tokens → refresh → /users/me → authenticated
 *   login: ROPC → tokens → /users/me
 *   logout: revoke refresh → очистка (WS/пуши придут на этапах 4/6)
 */

import { useSession, type SessionUser } from "../stores/session";
import { api } from "./api-client";
import {
  ropcLogin,
  refreshToken,
  revokeToken,
  exchangePkceCode,
  buildAuthorizeUrl,
  createPkceSession,
  AuthError,
  type PkceSession,
} from "./kc-auth";
import { clearTokens, loadTokens, saveTokens } from "./token-storage";
import type { TokenResponse } from "./kc-auth";

interface UserMe {
  id: string;
  username: string;
  display_name: string;
}

async function persistTokens(tokens: TokenResponse): Promise<void> {
  await saveTokens({
    access_token: tokens.access_token,
    refresh_token: tokens.refresh_token ?? "",
    access_expires_at: Date.now() + tokens.expires_in * 1000 - 30_000,
  });
}

async function fetchMe(accessToken: string): Promise<SessionUser> {
  const me = await api<UserMe>("/users/me", { accessToken });
  return { id: me.id, username: me.username, display_name: me.display_name };
}

/** ROPC-логин: нативная форма → KC token endpoint → /users/me. */
export async function login(username: string, password: string): Promise<void> {
  let tokens: TokenResponse;
  try {
    tokens = await ropcLogin(username, password);
  } catch (e) {
    // Fallback §3.2: ROPC отключён/недоступен (invalid_grant/403, кроме
    // «неверный логин-пароль» и network_error) → PKCE через Custom Tab.
    if (
      e instanceof AuthError &&
      e.status >= 400 &&
      e.status < 500 &&
      e.error !== "invalid_grant" &&
      e.error !== "network_error"
    ) {
      tokens = await loginViaPkce();
    } else {
      throw e;
    }
  }
  await persistTokens(tokens);
  const user = await fetchMe(tokens.access_token);
  useSession.getState().setUser(user);
  useSession.getState().setAuthenticated(true);
}

// ── PKCE-fallback (§3.2): Custom Tab → vibechat://callback → обмен кода ────
// sessionStorage для verifier/state — не Keystore (краткоживущие, только на
// время флоу); глубже UI-слоя не идём: openAuthSessionAsync открывает Chrome
// Custom Tab и ждёт redirect на vibechat://callback.

let pendingPkce: (PkceSession & { resolve: (tokens: TokenResponse) => void; reject: (e: unknown) => void }) | null = null;

/** Завершение PKCE-флоу: вызывается из deep link (app/_layout.tsx). */
export async function handlePkceRedirect(url: string): Promise<void> {
  if (!pendingPkce) return;
  const session = pendingPkce;
  pendingPkce = null;
  try {
    const params = new URL(url).searchParams;
    const error = params.get("error");
    if (error) {
      throw new AuthError(error, params.get("error_description") ?? "PKCE failed", 400);
    }
    const code = params.get("code");
    const state = params.get("state");
    if (!code) throw new AuthError("invalid_request", "Нет code в redirect", 400);
    if (state !== session.state) {
      throw new AuthError("invalid_grant", "state mismatch (CSRF)", 400);
    }
    const tokens = await exchangePkceCode(code, session.verifier);
    session.resolve(tokens);
  } catch (e) {
    session.reject(e);
  }
}

function loginViaPkce(): Promise<TokenResponse> {
  // expo-web-browser импорт ленивый: модуль тяжёлый, в основном флоу (ROPC) не нужен
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { openAuthSessionAsync } = require("expo-web-browser");
  return new Promise<TokenResponse>((resolve, reject) => {
    createPkceSession()
      .then(async (session) => {
        pendingPkce = { ...session, resolve, reject };
        const authorizeUrl = buildAuthorizeUrl(session);
        const result = await openAuthSessionAsync(authorizeUrl, "vibechat://callback");
        if (result.type !== "success" || !result.url) {
          pendingPkce = null;
          reject(new AuthError("pkce_cancelled", "Вход через браузер отменён", 0));
          return;
        }
        await handlePkceRedirect(result.url);
      })
      .catch((e) => {
        pendingPkce = null;
        reject(e);
      });
  });
}

/** Холодный старт: refresh из Keystore → /users/me. Не бросает — просто разлогинивает. */
export async function restoreSession(): Promise<void> {
  useSession.getState().setRestoring(true);
  try {
    const stored = await loadTokens();
    if (!stored || !stored.refresh_token) {
      useSession.getState().setAuthenticated(false);
      return;
    }
    const tokens = await refreshToken(stored.refresh_token);
    await persistTokens(tokens);
    const user = await fetchMe(tokens.access_token);
    useSession.getState().setUser(user);
    useSession.getState().setAuthenticated(true);
  } catch {
    await clearTokens();
    useSession.getState().setUser(null);
    useSession.getState().setAuthenticated(false);
  } finally {
    useSession.getState().setRestoring(false);
  }
}

/** Обновление access-токена для api-client (401 → refresh → retry). */
export async function refreshAccessToken(): Promise<string | null> {
  const stored = await loadTokens();
  if (!stored || !stored.refresh_token) return null;
  try {
    const tokens = await refreshToken(stored.refresh_token);
    await persistTokens(tokens);
    return tokens.access_token;
  } catch {
    await logoutLocal();
    return null;
  }
}

export async function getAccessToken(): Promise<string | null> {
  const stored = await loadTokens();
  if (!stored) return null;
  if (Date.now() < stored.access_expires_at) return stored.access_token;
  return refreshAccessToken();
}

/** Logout: revoke → очистка локального состояния (§3.2; пуши — этап 6). */
export async function logout(): Promise<void> {
  const stored = await loadTokens();
  if (stored?.refresh_token) await revokeToken(stored.refresh_token);
  await logoutLocal();
}

/** Локальная очистка без revoke (refresh не удался/токенов нет). */
export async function logoutLocal(): Promise<void> {
  await clearTokens();
  useSession.getState().setUser(null);
  useSession.getState().setAuthenticated(false);
}

export { AuthError };
