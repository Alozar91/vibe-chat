export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
  retryAfter: number | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    retryAfter: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.retryAfter = retryAfter;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

const CSRF_COOKIE = "vibe_csrf";

export function readCsrfToken(): string {
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(CSRF_COOKIE + "="));
  return match ? decodeURIComponent(match.split("=").slice(1).join("=")) : "";
}

let redirectingToLogin = false;

export function redirectToLogin() {
  if (redirectingToLogin) return;
  if (window.location.pathname.startsWith("/login")) return;
  redirectingToLogin = true;
  const next = window.location.pathname + window.location.search;
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

export function redirectToKeycloakLogin() {
  const origin = window.location.origin;
  window.location.href = `/v1/auth/login?origin=${encodeURIComponent(origin)}`;
}

interface ApiOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

const MUTATING = new Set(["POST", "PATCH", "PUT", "DELETE"]);

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const method = options.method || "GET";
  const headers: Record<string, string> = { ...options.headers };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (MUTATING.has(method)) {
    const token = readCsrfToken();
    if (token) headers["X-CSRF-Token"] = token;
  }

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "network_error", "Нет связи с сервером");
  }

  if (response.status === 401) {
    redirectToLogin();
    throw new ApiError(401, "unauthorized", "Требуется авторизация");
  }

  if (response.status === 204) return null as T;

  let payload: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const err =
      payload && typeof payload === "object" && "error" in payload
        ? (payload as { error: { code: string; message: string; details?: Record<string, unknown> } }).error
        : null;
    const retryAfterHeader = response.headers.get("Retry-After");
    const retryAfter = retryAfterHeader ? Number(retryAfterHeader) : null;
    throw new ApiError(
      response.status,
      err?.code || "internal_error",
      err?.message || `Ошибка ${response.status}`,
      err?.details || {},
      Number.isFinite(retryAfter) ? retryAfter : null,
    );
  }

  return payload as T;
}

export function buildQuery(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}
