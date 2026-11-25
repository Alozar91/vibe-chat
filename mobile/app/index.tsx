/**
 * Точка входа: guard сессии (Docs/android.md §3.6) + самодиагностика (§3.7).
 * Холодный старт: restoreSession (refresh → /users/me) → chats | login.
 */

import { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { router } from "expo-router";
import { runDiagnostics, type DiagnosticsResult } from "../src/services/diagnostics";
import { useSession } from "../src/stores/session";
import { restoreSession } from "../src/services/session-service";
import { theme, useThemedStyles } from "../src/theme";

export default function Index() {
  const authenticated = useSession((s) => s.authenticated);
  const restoring = useSession((s) => s.restoring);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResult | null>(null);
  const styles = useStyles();

  useEffect(() => {
    runDiagnostics().then(setDiagnostics);
    restoreSession();
  }, []);

  useEffect(() => {
    // guard: пока restoring — ждём; дальше auth → chats, иначе → login
    if (restoring || !diagnostics) return;
    if (authenticated) {
      router.replace("/(app)/chats");
    } else {
      router.replace("/login");
    }
  }, [restoring, authenticated, diagnostics]);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Vibe Chat</Text>
      {!diagnostics ? (
        <>
          <ActivityIndicator size="large" />
          <Text style={styles.hint}>Проверка конфига...</Text>
        </>
      ) : diagnostics.ok ? (
        <>
          <Text style={styles.ok}>✓ Бэкенд доступен</Text>
          <Text style={styles.ok}>✓ Хранилище файлов доступно</Text>
          <ActivityIndicator size="large" style={styles.spinner} />
          <Text style={styles.hint}>
            {restoring ? "Восстановление сессии..." : "Конфиг валиден, переход к входу..."}
          </Text>
        </>
      ) : (
        <Text style={styles.error}>{diagnostics.message}</Text>
      )}
    </View>
  );
}

const useStyles = () => useThemedStyles(() => StyleSheet.create({
  container: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 8, backgroundColor: theme.colors.background },
  title: { fontSize: 28, fontWeight: "700", marginBottom: 16, color: theme.colors.text },
  hint: { fontSize: 13, opacity: 0.6, color: theme.colors.textSecondary },
  ok: { fontSize: 14, color: theme.colors.accentGreen },
  error: { fontSize: 14, color: theme.colors.danger, textAlign: "center" },
  spinner: { marginTop: 12 },
}));
