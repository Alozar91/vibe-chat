/**
 * MMKV — персистентный оффлайн-кэш (Docs/android.md §3.4).
 * Сообщения/метаданные переживают перезапуск; холодный старт без сети
 * рендерит ленту из кэша, затем фоновое догоняние.
 */

import { MMKV } from "react-native-mmkv";

/** Отдельный инстанс под кэш данных (токены — только Keystore, §3.2!) */
export const storage = new MMKV({ id: "vibe-cache" });

/** Очистка кэша при logout (вход другим пользователем — данные не утекают) */
export function clearCacheStorage(): void {
  storage.clearAll();
}
