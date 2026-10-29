import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";

export const MEDIA_STALE_MS = 4 * 60_000;

export function useMediaUrl(path: string | null): string | null {
  const query = useQuery({
    queryKey: ["media", path],
    queryFn: async () => {
      const data = await api<{ url: string }>(path as string);
      return data.url;
    },
    enabled: !!path,
    staleTime: MEDIA_STALE_MS,
    gcTime: 10 * 60_000,
    retry: 1,
  });
  return query.data ?? null;
}

export async function resolveMediaUrl(path: string): Promise<string | null> {
  try {
    const data = await api<{ url: string }>(path);
    return data.url;
  } catch {
    return null;
  }
}
