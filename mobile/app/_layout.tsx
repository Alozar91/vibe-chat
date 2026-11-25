import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect, useRef, useState } from "react";
import { Linking, Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
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
  // Гейт версии (§3.8): блокирующий экран, пока min_version с сервера > собственной;
  // latest_version > собственной → неблокирующий баннер «доступна новая версия»
  const [versionBlocked, setVersionBlocked] = useState(false);
  const [versionMin, setVersionMin] = useState<string | null>(null);
  const [versionLatest, setVersionLatest] = useState<string | null>(null);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  // Проверка версии (§3.8): при старте и по кнопке «Проверить снова»
  const checkVersion = () => {
    setBannerDismissed(false);
    void fetchVersionGate().then((r) => {
      setVersionBlocked(r.blocked);
      setVersionMin(r.min);
      setVersionLatest(r.latest);
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
        <View style={{ flex: 1 }}>
          {versionLatest && !bannerDismissed ? (
            <UpdateBanner latest={versionLatest} onDismiss={() => setBannerDismissed(true)} />
          ) : null}
          <Stack>
            <Stack.Screen name="index" options={{ headerShown: false }} />
            <Stack.Screen name="login" options={{ title: "Вход" }} />
            <Stack.Screen name="register" options={{ title: "Регистрация" }} />
            <Stack.Screen name="(app)" options={{ headerShown: false }} />
          </Stack>
        </View>
      )}
    </PersistQueryClientProvider>
  );
}

/** Неблокирующий баннер «доступна новая версия» (§3.8, отложено до первого релиза —
 * теперь реализован): тап по тексту — открыть ссылку (если задана), ✕ — скрыть. */
function UpdateBanner({ latest, onDismiss }: { latest: string; onDismiss: () => void }) {
  const styles = useStyles();
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.banner, { paddingTop: insets.top + styles.banner.paddingVertical }]}>
      <Pressable
        style={styles.bannerBody}
        disabled={!config.appDownloadUrl}
        onPress={() => {
          if (config.appDownloadUrl) void Linking.openURL(config.appDownloadUrl as string);
        }}
      >
        <Text style={styles.bannerText}>
          {t("version.updateAvailable", { ver: latest })}
        </Text>
        {config.appDownloadUrl ? <Text style={styles.bannerAction}>{t("version.download")}</Text> : null}
      </Pressable>
      <Pressable hitSlop={8} onPress={onDismiss} accessibilityLabel={t("version.dismiss")}>
        <Text style={styles.bannerClose}>✕</Text>
      </Pressable>
    </View>
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
      banner: {
        flexDirection: "row",
        alignItems: "center",
        backgroundColor: theme.colors.bubbleOut,
        borderBottomWidth: 1,
        borderBottomColor: theme.colors.border,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.sm,
        gap: theme.spacing.sm,
      },
      bannerBody: { flex: 1, flexDirection: "row", alignItems: "center", gap: theme.spacing.sm },
      bannerText: { fontSize: theme.font.sm, color: theme.colors.text, flexShrink: 1 },
      bannerAction: {
        fontSize: theme.font.sm,
        color: theme.colors.primary,
        fontWeight: "700",
        textDecorationLine: "underline",
      },
      bannerClose: { fontSize: 16, color: theme.colors.textSecondary, paddingHorizontal: 4 },
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
