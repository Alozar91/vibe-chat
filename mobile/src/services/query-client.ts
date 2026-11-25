/**
 * QueryClient (TanStack Query v5) — синглтон приложения.
 * gcTime длинный (кэш в памяти + MMKV-persister); retry — 1 (быстрый отказ →
 * статус error и кнопка «повторить», §3.10).
 */

import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      gcTime: 30 * 60 * 1000,
      retry: 1,
      refetchOnWindowFocus: true,
      // оффлайн-кэш (§3.4): hydrate из MMKV рендерится сразу,
      // сеть может отсутствовать — не считаем это ошибкой рендера
    },
    mutations: {
      retry: 0, // ретрай отправки — только вручную (кнопка «повторить»)
    },
  },
});
