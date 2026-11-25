/**
 * Тема — только токены (§3.10: хардкод цветов в компонентах запрещён).
 * Светлая палитра, близкая к веб-фронтенду.
 */

export const theme = {
  colors: {
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
  },
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
