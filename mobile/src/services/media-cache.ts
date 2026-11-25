/**
 * Медиа-кэш (§3.4): thumbnails/картинки в CacheDirectory, LRU 500 МБ,
 * переживает перезапуск приложения (каталог кэша не чистится при закрытии).
 * Ключи — file_id / thumb_key; index в MMKV (vibe-cache).
 */

import * as FileSystem from "expo-file-system";
import { storage } from "./offline-cache";

const DIR = `${FileSystem.cacheDirectory}vibe-media/`;
const INDEX_KEY = "media-cache-index";
const MAX_TOTAL_BYTES = 500 * 1024 * 1024; // §3.4

interface IndexEntry {
  path: string;
  size: number;
  ts: number; // последний доступ (LRU)
}

type Index = Record<string, IndexEntry>;

let dirEnsured = false;

async function ensureDir(): Promise<void> {
  if (dirEnsured) return;
  const info = await FileSystem.getInfoAsync(DIR);
  if (!info.exists) await FileSystem.makeDirectoryAsync(DIR, { intermediates: true });
  dirEnsured = true;
}

function loadIndex(): Index {
  const raw = storage.getString(INDEX_KEY);
  if (!raw) return {};
  try {
    return JSON.parse(raw) as Index;
  } catch {
    return {};
  }
}

function saveIndex(index: Index): void {
  storage.set(INDEX_KEY, JSON.stringify(index));
}

async function prune(): Promise<void> {
  const index = loadIndex();
  const entries = Object.entries(index).sort((a, b) => a[1].ts - b[1].ts);
  let total = entries.reduce((sum, [, e]) => sum + e.size, 0);
  for (const [key, entry] of entries) {
    if (total <= MAX_TOTAL_BYTES) break;
    try {
      await FileSystem.deleteAsync(entry.path, { idempotent: true });
    } catch {
      // уже нет — ок
    }
    delete index[key];
    total -= entry.size;
  }
  saveIndex(index);
}

function record(key: string, path: string, size: number): void {
  const index = loadIndex();
  index[key] = { path, size, ts: Date.now() };
  saveIndex(index);
}

/** Локальный uri, если файл уже в кэше (перезапуск не перекачивает). */
export function cachedUri(key: string): string | null {
  const entry = loadIndex()[key];
  if (!entry) return null;
  // touch LRU синхронно (MMKV дёшев)
  const index = loadIndex();
  index[key] = { ...entry, ts: Date.now() };
  saveIndex(index);
  return entry.path;
}

/** Скачать в кэш (или вернуть существующий). Устойчиво к гонкам: последний win. */
export async function fetchToCache(key: string, url: string): Promise<string> {
  const existing = cachedUri(key);
  if (existing) return existing;
  await ensureDir();
  const path = `${DIR}${key}`;
  const res = await FileSystem.downloadAsync(url, path);
  const sizeInfo = await FileSystem.getInfoAsync(res.uri);
  record(key, path, sizeInfo.exists && "size" in sizeInfo ? sizeInfo.size : 0);
  void prune();
  return res.uri;
}
