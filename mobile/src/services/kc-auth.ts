/**
 * Keycloak token endpoint — ROPC (основной флоу) + refresh + PKCE-fallback
 * (Docs/android.md §3.2). Формат form-urlencoded, как у любого OAuth2 token endpoint.
 */

import * as Crypto from "expo-crypto";
import { config } from "./config";

export interface TokenResponse {
  access_token: string;
  refresh_token?: string;
  expires_in: number;
  refresh_expires_in?: number;
  token_type: string;
}

export class AuthError extends Error {
  constructor(
    public error: string,
    public errorDescription: string,
    public status: number
  ) {
    super(`${error}: ${errorDescription}`);
  }
}

async function tokenRequest(body: Record<string, string>): Promise<TokenResponse> {
  let response: Response;
  try {
    response = await fetch(config.kc.tokenEndpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        Accept: "application/json",
      },
      body: new URLSearchParams(body).toString(),
    });
  } catch {
    throw new AuthError("network_error", "Keycloak недоступен", 0);
  }

  const data = (await response.json().catch(() => ({}))) as {
    error?: string;
    error_description?: string;
    access_token?: string;
    refresh_token?: string;
    expires_in?: number;
    refresh_expires_in?: number;
    token_type?: string;
  };

  if (!response.ok || !data.access_token) {
    throw new AuthError(
      data.error ?? "unknown_error",
      data.error_description ?? `HTTP ${response.status}`,
      response.status
    );
  }

  return {
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    expires_in: data.expires_in ?? 300,
    refresh_expires_in: data.refresh_expires_in,
    token_type: data.token_type ?? "Bearer",
  };
}

/** ROPC: пароль проходит только через нативную форму в KC token endpoint (§3.2). */
export function ropcLogin(username: string, password: string): Promise<TokenResponse> {
  return tokenRequest({
    grant_type: "password",
    client_id: config.kcClientId,
    scope: "openid profile email",
    username,
    password,
  });
}

/** Refresh flow: обмен refresh-токена на новую пару. */
export function refreshToken(refresh_token: string): Promise<TokenResponse> {
  return tokenRequest({
    grant_type: "refresh_token",
    client_id: config.kcClientId,
    refresh_token,
  });
}

/** Revoke refresh-токена (logout, §3.2): ошибка не фатальна — локальная очистка всё равно идёт. */
export async function revokeToken(token: string): Promise<void> {
  try {
    await fetch(config.kc.revocationEndpoint ?? `${config.kcUrl}/realms/${config.kcRealm}/protocol/openid-connect/revoke`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: config.kcClientId,
        token,
      }).toString(),
    });
  } catch {
  }
}

// ── PKCE-fallback (§3.2): если ROPC недоступен — Custom Tab ────────────────

const PKCE_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";

function randomPkceString(length: number): string {
  const bytes = Crypto.getRandomBytes(length);
  let result = "";
  for (let i = 0; i < length; i++) {
    result += PKCE_CHARSET[bytes[i] % PKCE_CHARSET.length];
  }
  return result;
}

/** S256: BASE64URL(SHA256(verifier)) без паддинга. */
async function s256Challenge(verifier: string): Promise<string> {
  const digest = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    verifier,
    { encoding: Crypto.CryptoEncoding.BASE64 }
  );
  // BASE64 → BASE64URL и срез паддинга (RFC 7636)
  return digest.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export interface PkceSession {
  verifier: string;
  challenge: string;
  state: string;
}

/** Подготовка PKCE-параметров (вызывается до открытия Custom Tab). */
export async function createPkceSession(): Promise<PkceSession> {
  const verifier = randomPkceString(64);
  const challenge = await s256Challenge(verifier);
  const state = randomPkceString(16);
  return { verifier, challenge, state };
}

/** URL authorize-запроса для Custom Tab (KC выдаёт refresh и без offline_access). */
export function buildAuthorizeUrl(session: PkceSession): string {
  const params = new URLSearchParams({
    client_id: config.kcClientId,
    response_type: "code",
    scope: "openid profile email",
    redirect_uri: "vibechat://callback",
    code_challenge: session.challenge,
    code_challenge_method: "S256",
    state: session.state,
  });
  return `${config.kc.authorizeEndpoint}?${params.toString()}`;
}

/** Обмен кода на токены (redirect попал в app по vibechat://callback). */
export function exchangePkceCode(code: string, verifier: string): Promise<TokenResponse> {
  return tokenRequest({
    grant_type: "authorization_code",
    client_id: config.kcClientId,
    redirect_uri: "vibechat://callback",
    code,
    code_verifier: verifier,
  });
}
