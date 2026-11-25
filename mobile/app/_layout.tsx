import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect, useRef, useState } from "react";
import { Linking, Pressable, StyleSheet, Text, View } from "react-native";
import { queryClient } from "../src/services/query-client";
import { createQueryPersister } from "../src/services/query-persister";
import { storage } from "../src/services/offline-cache";
import { installRealtimeSync } from "../src/services/realtime-sync";
import { wsClient } from "../src/services/ws-client";
import { useSession } from "../src/stores/session";
import { useRealtime } from "../src/stores/realtime";
import { theme, useThemedStyles, useThemeStore } from "../src/theme";
import { t } from "../src/i18n/ru";
import { handlePkceRedirect } from "../src/services/session-service";
import { installPushHandlers } from "../src/services/push-service";
import {
  fetchVersionGate,
  ownVersion,
} from "../src/services/app-version";
import { config } from "../src/services/config";

const persister = createQueryPersister(storage);

export default function RootLayout() {
  const authenticated = useSession((s) => s.authenticated);
  const resolvedTheme = useThemeStore((s) => s.resolved);
  const syncRef = useRef(false);
  const pushRef = useRef(false);
  // Гейт версии (§3.8): блокирующий экран, пока min_version с сервера > собственной
  const [versionBlocked, setVersionBlocked] = useState(false);
  const [versionMin, setVersionMin] = useState<string | null>(null);

  // Проверка версии (§3.8): при старте и по кнопке «Проверить снова»
  const checkVersion = () => {
    void fetchVersionGate().then((r) => {
      setVersionBlocked(r.blocked);
      setVersionMin(r.min);
    });
  };
  useEffect(checkVersion, []);

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
      {versionBlocked ? (
        <VersionGate min={versionMin} onRetry={checkVersion} />
      ) : (
        <Stack>
          <Stack.Screen name="index" options={{ headerShown: false }} />
          <Stack.Screen name="login" options={{ title: "Вход" }} />
          <Stack.Screen name="register" options={{ title: "Регистрация" }} />
          <Stack.Screen name="(app)" options={{ headerShown: false }} />
        </Stack>
      )}
    </PersistQueryClientProvider>
  );
}

/** Блокирующий экран устаревшей версии (§3.8): без навигации и входа. */
function VersionGate({ min, onRetry }: { min: string | null; onRetry: () => void }) {
  const styles = useStyles();
  return (
    <View style={styles.gate}>
      <Text style={styles.title}>{t("version.blockedTitle")}</Text>
      <Text style={styles.text}>
        {t("version.blockedText", { own: ownVersion, min: min ?? "" })}
      </Text>
      {config.appDownloadUrl ? (
        <Pressable
          style={styles.button}
          onPress={() => {
            void Linking.openURL(config.appDownloadUrl as string);
          }}
        >
          <Text style={styles.buttonText}>{t("version.download")}</Text>
        </Pressable>
      ) : (
        <Text style={styles.hint}>{t("version.noLink")}</Text>
      )}
      <Pressable style={styles.retryButton} onPress={onRetry}>
        <Text style={styles.retryText}>{t("version.retry")}</Text>
      </Pressable>
    </View>
  );
}

const useStyles = () =>
  useThemedStyles(() =>
    StyleSheet.create({
      gate: {
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: theme.colors.background,
        paddingHorizontal: theme.spacing.xl,
      },
      title: {
        fontSize: theme.font.xl + 2,
        fontWeight: "700",
        color: theme.colors.text,
        marginBottom: theme.spacing.md,
      },
      text: {
        fontSize: theme.font.md,
        color: theme.colors.text,
        textAlign: "center",
        marginBottom: theme.spacing.lg,
      },
      button: {
        backgroundColor: theme.colors.primary,
        borderRadius: theme.radius.md,
        paddingHorizontal: theme.spacing.xl,
        paddingVertical: theme.spacing.sm + 2,
        marginBottom: theme.spacing.md,
      },
      buttonText: {
        color: theme.colors.primaryText,
        fontSize: theme.font.md,
        fontWeight: "600",
      },
      hint: {
        fontSize: theme.font.sm,
        color: theme.colors.textSecondary,
        textAlign: "center",
        marginBottom: theme.spacing.md,
      },
      retryButton: {
        paddingVertical: theme.spacing.sm,
        paddingHorizontal: theme.spacing.lg,
      },
      retryText: {
        fontSize: theme.font.md,
        color: theme.colors.primary,
      },
    })
  );
