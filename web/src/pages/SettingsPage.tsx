import { useEffect, useState } from "react";
import { Button, PageBack } from "../components/ui";

type Theme = "light" | "dark" | "system";

const KEY = "vibe.theme";

function applyTheme(theme: Theme) {
  const dark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

export function initTheme() {
  const saved = (localStorage.getItem(KEY) as Theme | null) || "system";
  applyTheme(saved);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if ((localStorage.getItem(KEY) as Theme | null) === "system") applyTheme("system");
  });
}

export function SettingsPage() {
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem(KEY) as Theme | null) || "system");
  const [sound, setSound] = useState(() => localStorage.getItem("vibe.sound") !== "off");

  useEffect(() => {
    localStorage.setItem(KEY, theme);
    applyTheme(theme);
  }, [theme]);

  return (
    <div className="page">
      <div className="page-narrow">
        <PageBack />
        <h2>Настройки</h2>

        <div className="field">
          <label>Тема</label>
          <div style={{ display: "flex", gap: 8 }}>
            {(["light", "dark", "system"] as Theme[]).map((value) => (
              <Button key={value} variant={theme === value ? "primary" : "default"} onClick={() => setTheme(value)}>
                {value === "light" ? "Светлая" : value === "dark" ? "Тёмная" : "Системная"}
              </Button>
            ))}
          </div>
        </div>

        <div className="notification-row">
          <span>Звук новых сообщений</span>
          <Button
            className="sm"
            onClick={() => {
              const next = !sound;
              setSound(next);
              localStorage.setItem("vibe.sound", next ? "on" : "off");
            }}
          >
            {sound ? "Включён" : "Выключен"}
          </Button>
        </div>
      </div>
    </div>
  );
}
