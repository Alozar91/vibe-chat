import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect, useRef } from "react";
import { Linking } from "react-native";
import { queryClient } from "../src/services/query-client";
import { createQueryPersister } from "../src/services/query-persister";
import { storage } from "../src/services/offline-cache";
import { installRealtimeSync } from "../src/services/realtime-sync";
import { wsClient } from "../src/services/ws-client";
import { useSession } from "../src/stores/session";
import { useRealtime } from "../src/stores/realtime";
import { useThemeStore } from "../src/theme";
import { handlePkceRedirect } from "../src/services/session-service";
import { installPushHandlers } from "../src/services/push-service";

const persister = createQueryPersister(storage);

export default function RootLayout() {
  const authenticated = useSession((s) => s.authenticated);
  const resolvedTheme = useThemeStore((s) => s.resolved);
  const syncRef = useRef(false);
  const pushRef = useRef(false);

  // Обработчики пушей (§3.5) — один раз: foreground/background/onOpenApp/холодный старт
  useEffect(() => {
    if (pushRef.current) return;
    pushRef.current = true;
    installPushHandlers();
  }, []);

  // PKCE-fallback (§3.2): redirect vibechat://callback приходит deep link'ом.
  // openAuthSessionAsync обычно сам возвращает URL, но cold-start (процесс убит
  // пока открыт Custom Tab) доставляет redirect только через Linking.
  useEffect(() => {
    const sub = Linking.addEventListener("url", ({ url }) => {
      if (url.startsWith("vibechat://")) {
        handlePkceRedirect(url).catch(() => {});
      }
    });
    return () => sub.remove();
  }, []);

  // Диспетчер realtime — один раз (§3.3: одна точка диспетчеризации)
  useEffect(() => {
    if (syncRef.current) return;
    syncRef.current = true;
    installRealtimeSync(queryClient);
    // чистка протухшего typing раз в секунду (как в вебе)
    const timer = setInterval(() => useRealtime.getState().expireTyping(), 1000);
    return () => clearInterval(timer);
  }, []);

  // WS-жизненный цикл по сессии: connect при входе, disconnect при logout (§3.3)
  useEffect(() => {
    if (authenticated) {
      void wsClient.connect();
      return () => wsClient.disconnect();
    }
    useRealtime.getState().clear();
  }, [authenticated]);

  return (
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{
        persister,
        maxAge: 24 * 60 * 60 * 1000, // сутки; старше — кэш не hydrate'ится
        // холодный старт в оффлайне: hydrate'им даже без сети, reconnect тревит
        buster: "",
      }}
    >
      <StatusBar
        style={resolvedTheme === "dark" ? "light" : "dark"}
        backgroundColor={resolvedTheme === "dark" ? "#09090b" : "#ffffff"}
      />
      <Stack>
        <Stack.Screen name="index" options={{ headerShown: false }} />
        <Stack.Screen name="login" options={{ title: "Вход" }} />
        <Stack.Screen name="register" options={{ title: "Регистрация" }} />
        <Stack.Screen name="(app)" options={{ headerShown: false }} />
      </Stack>
    </PersistQueryClientProvider>
  );
}
