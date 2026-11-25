/**
 * Сессия — Zustand store (Docs/android.md §3.1: Zustand — runtime-состояние,
 * токены живут в Keychain, в сторе только факт наличия + профиль).
 */

import { create } from "zustand";

export interface SessionUser {
  id: string;
  username: string;
  display_name: string;
}

interface SessionState {
  /** Есть ли живая сессия (токены в Keychain); сам access/refresh тут не хранится */
  authenticated: boolean;
  user: SessionUser | null;
  /** true при загрузке холодного старта (refresh → /users/me) */
  restoring: boolean;

  setAuthenticated: (authenticated: boolean) => void;
  setUser: (user: SessionUser | null) => void;
  setRestoring: (restoring: boolean) => void;
}

export const useSession = create<SessionState>((set) => ({
  authenticated: false,
  user: null,
  // этап 1: восстановление сессии ещё не реализовано (этап 2) — сразу считаем cold-start завершённым
  restoring: false,

  setAuthenticated: (authenticated) => set({ authenticated }),
  setUser: (user) => set({ user }),
  setRestoring: (restoring) => set({ restoring }),
}));
