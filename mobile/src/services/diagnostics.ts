/**
 * Самодиагностика конфига на старте (Docs/android.md §3.7):
 * доступность REST и host'а Silo — понятное сообщение вместо runtime-падений.
 */

import { config } from "./config";

export interface DiagnosticsResult {
  ok: boolean;
  apiReachable: boolean;
  siloReachable: boolean;
  message?: string;
}

export async function runDiagnostics(): Promise<DiagnosticsResult> {
  const result: DiagnosticsResult = { ok: false, apiReachable: false, siloReachable: false };

  // fetch без таймаута висит минутами на недоступном хосте — режем 5 секундами.
  // AbortSignal.timeout в Hermes RN 0.79 отсутствует → AbortController + setTimeout
  const probe = (url: string): Promise<boolean> =>
    new Promise((resolve) => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 5000);
      fetch(url, { method: "HEAD", signal: controller.signal })
        .then(() => resolve(true))
        .catch(() => resolve(false))
        .finally(() => clearTimeout(timer));
    });

  // REST: любой ответ (даже 404) = хост доступен
  result.apiReachable = await probe(`${config.apiBase}/openapi.json`);
  // Silo: host из SILO_PUBLIC_URL должен отвечать (он будет в presigned URL)
  result.siloReachable = await probe(config.siloPublicUrl);

  result.ok = result.apiReachable && result.siloReachable;

  if (!result.ok) {
    const problems: string[] = [];
    if (!result.apiReachable) problems.push("бэкенд недоступен");
    if (!result.siloReachable) problems.push("хранилище файлов недоступно");
    result.message = `Проблема: ${problems.join(", ")}. Проверьте конфиг (.env) и сеть.`;
  }

  return result;
}
