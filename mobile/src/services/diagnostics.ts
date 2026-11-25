/**
 * Самодиагностика на старте (Docs/android.md §3.7): доступность REST бэкенда.
 * Silo клиенту не нужен (URL вложений приходят в сериализации от бэкенда, §19.2);
 * подключение к серверу — задача онбординга (`server-profile.ts`).
 */

import { config } from "./config";

export interface DiagnosticsResult {
  ok: boolean;
  apiReachable: boolean;
  message?: string;
}

export async function runDiagnostics(): Promise<DiagnosticsResult> {
  const result: DiagnosticsResult = { ok: false, apiReachable: false };

  // fetch без таймаута висит минутами на недоступном хосте — режем 5 секундами.
  // AbortSignal.timeout в Hermes RN 0.79 отсутствует → AbortController + setTimeout
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    // REST: любой ответ (даже 404) = хост доступен
    const res = await fetch(`${config.apiBase}/openapi.json`, {
      method: "HEAD",
      signal: controller.signal,
    });
    result.apiReachable = true;
    void res;
  } catch {
    result.apiReachable = false;
  } finally {
    clearTimeout(timer);
  }

  result.ok = result.apiReachable;
  if (!result.ok) {
    result.message = "Сервер недоступен. Проверьте сеть и адрес сервера";
  }
  return result;
}
