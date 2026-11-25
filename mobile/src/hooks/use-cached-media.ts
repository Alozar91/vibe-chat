/**
 * useCachedMedia — presigned URL → локальный файл в медиа-кэше (§3.4).
 * Переживает перезапуск (CacheDirectory + index в MMKV); пока качается — null.
 */

import { useEffect, useState } from "react";
import { cachedUri, fetchToCache } from "../services/media-cache";

export function useCachedMedia(key: string | null, url: string | null): string | null {
  const [uri, setUri] = useState<string | null>(() => (key ? cachedUri(key) : null));

  useEffect(() => {
    if (!key || !url) return;
    let alive = true;
    const local = cachedUri(key);
    if (local) {
      setUri(local);
      return;
    }
    setUri(null);
    fetchToCache(key, url)
      .then((u) => {
        if (alive) setUri(u);
      })
      .catch(() => {
        // сеть пропала — остаёмся с blurhash/плейсхолдером
        if (alive) setUri(null);
      });
    return () => {
      alive = false;
    };
  }, [key, url]);

  return uri;
}
