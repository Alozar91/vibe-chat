/**
 * Экран входа (этап 2, Docs/android.md §3.2): нативная форма, ROPC.
 * Пароль не покидает приложение, кроме как в KC token endpoint (direct grant).
 */

import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { router } from "expo-router";
import { ApiError } from "../src/services/api-client";
import { AuthError } from "../src/services/kc-auth";
import { login } from "../src/services/session-service";
import { theme, useThemedStyles } from "../src/theme";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const styles = useStyles();

  const submit = async () => {
    if (!username.trim() || !password) {
      setError("Введите логин и пароль");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
      router.replace("/(app)/chats");
    } catch (e) {
      if (e instanceof AuthError) {
        if (e.error === "invalid_grant") setError("Неверный логин или пароль");
        else if (e.error === "network_error") setError("Keycloak недоступен — проверьте сеть");
        else setError(`Ошибка входа: ${e.errorDescription}`);
      } else if (e instanceof ApiError && e.status === 0) {
        setError("Нет соединения с бэкендом");
      } else {
        setError("Ошибка входа");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "android" ? undefined : "padding"}
    >
      <Text style={styles.title}>Вход</Text>

      <TextInput
        style={styles.input}
        placeholder="Логин"
        autoCapitalize="none"
        autoCorrect={false}
        value={username}
        onChangeText={setUsername}
        editable={!busy}
      />
      <TextInput
        style={styles.input}
        placeholder="Пароль"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
        editable={!busy}
      />

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <Pressable style={[styles.button, busy && styles.buttonDisabled]} onPress={submit} disabled={busy}>
        {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Войти</Text>}
      </Pressable>

      <Pressable onPress={() => router.push("/register")} disabled={busy}>
        <Text style={styles.link}>Создать аккаунт</Text>
      </Pressable>
    </KeyboardAvoidingView>
  );
}

const useStyles = () => useThemedStyles(() => StyleSheet.create({
  container: { flex: 1, justifyContent: "center", padding: 24, gap: 12, backgroundColor: theme.colors.background },
  title: { fontSize: 28, fontWeight: "700", textAlign: "center", marginBottom: 16, color: theme.colors.text },
  input: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
    backgroundColor: theme.colors.background,
    color: theme.colors.text,
  },
  button: {
    backgroundColor: theme.colors.primary,
    borderRadius: 8,
    paddingVertical: 14,
    alignItems: "center",
    marginTop: 8,
  },
  buttonDisabled: { opacity: 0.6 },
  buttonText: { color: theme.colors.primaryText, fontSize: 16, fontWeight: "600" },
  error: { color: theme.colors.danger, fontSize: 14, textAlign: "center" },
  link: { color: theme.colors.primary, fontSize: 15, textAlign: "center", marginTop: 8 },
}));
