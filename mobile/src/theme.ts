/**
 * Тема — только токены (§3.10: хардкод цветов в компонентах запрещён).
 * Светлая/тёмная палитры, близкие к веб-фронтенду; режим light|dark|system.
 *
 * Механика смены: `applyTheme()` перезаписывает `theme.colors` НА МЕСТЕ (identity
 * сохраняется — замыкания компонентов не ломаются) и бампает version в сторе;
 * компоненты берут стили через `useThemedStyles` (подписка на version) — при
 * смене темы всё перерисовывается с новой палитрой без правки мест вызова.
 */

import { useMemo } from "react";
import { Appearance } from "react-native";
import { create } from "zustand";
import { storage } from "./services/offline-cache";

export type ThemeMode = "light" | "dark" | "system";

const light = {
  background: "#ffffff",
  surface: "#f4f4f5",
  surfaceActive: "#e4e4e7",
  text: "#18181b",
  textSecondary: "#71717a",
  textInverse: "#ffffff",
  primary: "#2563eb",
  primaryText: "#ffffff",
  danger: "#dc2626",
  border: "#e4e4e7",
  bubbleOut: "#dbeafe",
  bubbleIn: "#f4f4f5",
  accentGreen: "#16a34a",
  badge: "#2563eb",
  errorBg: "#fee2e2",
};

// zinc-950/900/800 + синие акценты ярче; textInverse остаётся белым (на primary)
const dark = {
  background: "#09090b",
  surface: "#18181b",
  surfaceActive: "#27272a",
  text: "#fafafa",
  textSecondary: "#a1a1aa",
  textInverse: "#ffffff",
  primary: "#3b82f6",
  primaryText: "#ffffff",
  danger: "#ef4444",
  border: "#27272a",
  bubbleOut: "#1e3a8a",
  bubbleIn: "#18181b",
  accentGreen: "#22c55e",
  badge: "#3b82f6",
  errorBg: "#450a0a",
};

const PALETTES = { light, dark };

export const theme = {
  colors: { ...light },
  radius: {
    sm: 6,
    md: 10,
    lg: 16,
    full: 9999,
  },
  spacing: {
    xs: 4,
    sm: 8,
    md: 12,
    lg: 16,
    xl: 24,
  },
  font: {
    sm: 12,
    md: 14,
    lg: 16,
    xl: 18,
  },
} as const;

interface ThemeState {
  mode: ThemeMode;
  resolved: "light" | "dark";
  /** счётчик применённых палитр — ключ мемоизации useThemedStyles */
  version: number;
}

export const useThemeStore = create<ThemeState>(() => ({
  mode: "system",
  resolved: "light",
  version: 0,
}));

function resolve(mode: ThemeMode): "light" | "dark" {
  return mode === "system" ? (Appearance.getColorScheme() ?? "light") : mode;
}

/** Применить режим: перезапись colors на месте + version++ + persist. */
export function applyTheme(mode: ThemeMode) {
  const resolved = resolve(mode);
  Object.assign(theme.colors, PALETTES[resolved]);
  storage.set("theme_mode", mode);
  useThemeStore.setState({ mode, resolved, version: useThemeStore.getState().version + 1 });
}

/** Инициализация на старте (index.js, до первого рендера): MMKV + listener system-режима. */
export function initTheme() {
  const saved = storage.getString("theme_mode") as ThemeMode | undefined;
  applyTheme(saved ?? "system");
  Appearance.addChangeListener(() => {
    if (useThemeStore.getState().mode === "system") {
      applyTheme("system");
    }
  });
}

/**
 * Стили, перестраиваемые при смене темы. Использование:
 *   const useStyles = () => useThemedStyles(() => StyleSheet.create({ ... }));
 *   // в теле компонента: const styles = useStyles();
 * Все места вызова `styles.x` остаются без изменений.
 */
export function useThemedStyles<T>(create: () => T): T {
  const version = useThemeStore((s) => s.version);
  return useMemo(create, [version]);
}
