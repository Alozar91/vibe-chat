/**
 * api-client — базовый REST-клиент (Docs/android.md §3.1).
 * Токен: из session-service; 401 → refresh → один retry; повторный 401 → разлогин.
 */

import { config } from "./config";
import { useSession } from "../stores/session";
import { getAccessToken, refreshAccessToken } from "./session-service";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
  }
}

interface ApiOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE" | "PUT";
  body?: unknown;
  /** явный токен (перекрывает автоподстановку из Keychain) */
  accessToken?: string;
  /** доп. заголовки (Idempotency-Key, §6) */
  headers?: Record<string, string>;
  /** внутренний флаг: повтор после refresh — чтобы не зациклиться */
  _retried?: boolean;
}

async function request<T>(path: string, options: ApiOptions): Promise<T> {
  const { method = "GET", body, accessToken, headers: extraHeaders, _retried } = options;

  const headers: Record<string, string> = {
    Accept: "application/json",
    ...extraHeaders,
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (!accessToken && !_retried) {
    const auto = await getAccessToken();
    if (auto) headers.Authorization = `Bearer ${auto}`;
  } else if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  let response: Response;
  try {
    response = await fetch(`${config.apiBase}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    // сеть недоступна (§3.10: snackbar «нет соединения», не блокирует UI)
    throw new ApiError(0, "Нет соединения");
  }

  if (response.status === 401 && !_retried) {
    // 401 → refresh → один retry; повторный 401 → разлогин (§3.2)
    const fresh = await refreshAccessToken();
    if (fresh) return request<T>(path, { ...options, _retried: true });
    useSession.getState().setAuthenticated(false);
    useSession.getState().setUser(null);
    throw new ApiError(401, "Сессия истекла");
  }

  if (!response.ok) {
    let message = `Ошибка ${response.status}`;
    try {
      const data = (await response.json()) as { detail?: string };
      if (data?.detail) message = data.detail;
    } catch {
    }
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  return request<T>(path, options);
}

// --- Шорткаты (удобство вызовов в endpoints.ts) ---

export const apiClient = {
  get: <T>(path: string, options: ApiOptions = {}) => request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, headers?: Record<string, string>) =>
    request<T>(path, { method: "POST", body, headers }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
