/**
 * QueryClient + MMKV-persister (§3.4): лента и списки переживают перезапуск.
 * createAsyncStoragePersister принимает sync storage тоже (MMKV getString/set).
 * Кэш сериализуется с дебаунсом 1 с; рестарт без сети → hydrate.
 */

import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import type { MMKV } from "react-native-mmkv";

const MMKV_PERSISTER_KEY = "vibe-query-cache";

function createMmkvStorage(mmkv: MMKV) {
  return {
    getItem: (key: string) => mmkv.getString(key) ?? null,
    setItem: (key: string, value: string) => mmkv.set(key, value),
    removeItem: (key: string) => mmkv.delete(key),
  };
}

export function createQueryPersister(mmkv: MMKV) {
  return createAsyncStoragePersister({
    storage: createMmkvStorage(mmkv),
    key: MMKV_PERSISTER_KEY,
    throttleTime: 1000,
  });
}
