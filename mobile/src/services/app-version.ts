/**
 * Проверка версии приложения при старте (§3.8, этап 8).
 *
 * `GET /app/version` (без аутентификации) отдаёт `{min_version, latest_version}`.
 * Своя версия — versionName из app.json (запекается в бандл через expo-constants).
 * (Release-механика: env-значения пробрасываются в оболочке перед gradlew —
 * @expo/env в export:embed не находит .env от projectRoot android/.)
 * `min_version` пуст или сервер недоступен → гейт открыт (fail-open: если
 * бэкенда нет, блокировать приложение нечем и незачем). Сравнение —
 * семантическое по versionName; versionCode монотонный, но не участвует
 * (гейт честнее требовать семантический минимум, чем код сборки).
 */

import Constants from "expo-constants";
import { config } from "./config";

/** versionName этой сборки (из app.json, запекается при сборке). */
export const ownVersion: string = Constants.expoConfig?.version ?? "0.0.0";

interface VersionGateResult {
  /** true — версия ниже минимально поддерживаемой, показать блокирующий экран. */
  blocked: boolean;
  /** min_version с сервера (для текста на блокирующем экране). */
  min: string | null;
  /** latest_version с сервера (для неблокирующего баннера «доступна новая версия»). */
  latest: string | null;
}

function parseSemver(value: string): [number, number, number] {
  const parts = value.trim().split(".").map((p) => parseInt(p, 10) || 0);
  return [parts[0] ?? 0, parts[1] ?? 0, parts[2] ?? 0];
}

/** a < b по семантике X.Y.Z. */
export function isSemverBelow(a: string, b: string): boolean {
  const pa = parseSemver(a);
  const pb = parseSemver(b);
  for (let i = 0; i < 3; i++) {
    if (pa[i] !== pb[i]) return pa[i] < pb[i];
  }
  return false;
}

export async function fetchVersionGate(): Promise<VersionGateResult> {
  const open: VersionGateResult = { blocked: false, min: null, latest: null };
  try {
    const res = await fetch(`${config.apiBase}/app/version`);
    if (!res.ok) return open;
    const data = (await res.json()) as { min_version?: string; latest_version?: string };
    const min = data.min_version ?? "";
    const latest = data.latest_version ?? "";
    const blocked = !min ? false : isSemverBelow(ownVersion, min);
    return {
      blocked,
      min: min || null,
      // баннер показываем только если последняя версия реально новее собственной
      latest: latest && isSemverBelow(ownVersion, latest) ? latest : null,
    };
  } catch {
    // сервер недоступен — fail-open (§3.8: блокируем только по явному min_version)
    return open;
  }
}
