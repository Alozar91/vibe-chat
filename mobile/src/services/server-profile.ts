/**
 * Профиль сервера (Docs/concept.md §19.3, Docs/android.md §3.13): клиент знает
 * один URL, всё остальное рассказывает GET /server/info. Хранится в MMKV
 * (чувствительность уровня «пароль от Wi-Fi»; токены аккаунта — в Keychain).
 *
 * Адрес может быть origin (`https://host`) или префиксом, под которым смонтирован
 * бэкенд (`https://host/chat` на текущем стенде); каноническая схема — origin.
 * Валидация: https-only в релизе (решение §19.3); в debug разрешён http к dev-хостам.
 */

import { MMKV } from "react-native-mmkv";
import { create } from "zustand";

export interface FirebaseClientConfig {
  project_id: string;
  api_key: string;
  app_id: string;
  sender_id: string;
  storage_bucket: string;
}

export interface PushInfo {
  driver: string;
  firebase: FirebaseClientConfig | null;
}

export interface ServerProfile {
  /** Адрес, который ввёл пользователь (как есть, без /api/v1) */
  baseUrl: string;
  /** Кодовое слово сервера, если потребовалось (пусто = не требуется) */
  joinCode: string;
  /** Человекочитаемое имя инсталляции (пусто = hostname) */
  name: string;
  kcUrl: string;
  realm: string;
  push: PushInfo;
  minVersion: string;
  latestVersion: string;
  appDownloadUrl: string;
}

const mmkv = new MMKV({ id: "vibe-server" });
const KEY = "server-profile";

interface ServerProfileState {
  profile: ServerProfile | null;
  set: (profile: ServerProfile | null) => void;
}

/** Реактивный доступ к профилю (_layout решает connect vs app; конфиг читает
 * getState() синхронно). set(null) — смена сервера: чистит и MMKV. */
export const useServerProfile = create<ServerProfileState>((set) => ({
  profile: loadServerProfile(),
  set: (profile) => {
    if (profile) saveServerProfile(profile);
    else clearServerProfile();
    set({ profile });
  },
}));

export function loadServerProfile(): ServerProfile | null {
  const raw = mmkv.getString(KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as ServerProfile;
  } catch {
    return null;
  }
}

/** Синхронный снапшот профиля (конфиг читает через это). */
export function getServerProfile(): ServerProfile | null {
  return useServerProfile.getState().profile;
}

export function saveServerProfile(profile: ServerProfile): void {
  mmkv.set(KEY, JSON.stringify(profile));
}

export function clearServerProfile(): void {
  mmkv.delete(KEY);
}

/** Ошибка подключения (текст — уже по-русски, для показа в UI). */
export class ConnectError extends Error {}

/** Схема → ws/wss (§3.13: WS выводится из того же адреса). */
export function wsSchemeFor(url: string): string {
  return url.startsWith("https://") ? "wss://" : "ws://";
}

/**
 * Нормализация введённого адреса + валидация. Без схемы — https:// по умолчанию.
 * Релиз принимает только https:// (решение §19.3); debug — и http:// (dev-хосты
 * дополнительно ограничены NSC debug-сборки).
 */
export function normalizeServerUrl(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, "");
  if (!trimmed) throw new ConnectError("Введите адрес сервера");
  const withScheme = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  let parsed: URL;
  try {
    parsed = new URL(withScheme);
  } catch {
    throw new ConnectError("Некорректный адрес сервера");
  }
  if (parsed.protocol === "http:") {
    if (!__DEV__) throw new ConnectError("Поддерживаются только https:// адреса");
  }
  if (!parsed.hostname.includes(".")) {
    // голый hostname без точки (кроме localhost/dev) — почти наверняка опечатка
    if (!["localhost", "10.0.2.2"].includes(parsed.hostname)) {
      throw new ConnectError("Укажите полное имя хоста или IP-адрес");
    }
  }
  // схемо-специфичный формат обратно в строку (без query/fragment)
  return `${parsed.protocol}//${parsed.host}${parsed.pathname.replace(/\/+$/, "")}`;
}

interface ServerInfoRaw {
  name?: string;
  kc_url?: string;
  realm?: string;
  push?: { driver?: string; firebase?: FirebaseClientConfig | null };
  min_version?: string;
  latest_version?: string;
  app_download_url?: string;
}

/**
 * Подключение к серверу: нормализация адреса → GET /server/info (+ X-Vibe-Join,
 * если код введён) → профиль. Бросает ConnectError с текстом для UI.
 */
export async function connectServer(rawUrl: string, joinCode: string): Promise<ServerProfile> {
  const base = normalizeServerUrl(rawUrl);
  const url = `${base}/api/v1/server/info`;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (joinCode.trim()) headers["X-Vibe-Join"] = joinCode.trim();

  let resp: Response;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      resp = await fetch(url, { headers, signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
  } catch {
    throw new ConnectError("Сервер недоступен. Проверьте адрес и сеть");
  }

  if (resp.status === 403) {
    // сервер требует кодовое слово (§19.5); 429 — брутфорс-защита
    throw new ConnectError("Сервер требует кодовое слово. Введите его и повторите");
  }
  if (resp.status === 429) {
    throw new ConnectError("Слишком много попыток. Подождите минуту и повторите");
  }
  if (!resp.ok) {
    throw new ConnectError(`Это не сервер Vibe Chat (HTTP ${resp.status})`);
  }

  let info: ServerInfoRaw;
  try {
    info = (await resp.json()) as ServerInfoRaw;
  } catch {
    throw new ConnectError("Ответ сервера не распознан");
  }
  if (!info.kc_url || !info.realm) {
    throw new ConnectError("Это не сервер Vibe Chat");
  }

  const profile: ServerProfile = {
    baseUrl: base,
    joinCode: joinCode.trim(),
    name: info.name ?? "",
    kcUrl: info.kc_url,
    realm: info.realm,
    push: {
      driver: info.push?.driver ?? "off",
      firebase: info.push?.firebase ?? null,
    },
    minVersion: info.min_version ?? "",
    latestVersion: info.latest_version ?? "",
    appDownloadUrl: info.app_download_url ?? "",
  };
  saveServerProfile(profile);
  return profile;
}

/** Hostname для отображения (имя инсталляции или host из URL). */
export function serverDisplayName(profile: ServerProfile): string {
  if (profile.name) return profile.name;
  try {
    return new URL(profile.baseUrl).host;
  } catch {
    return profile.baseUrl;
  }
}
