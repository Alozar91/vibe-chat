/**
 * Нативная регистрация (этап 2, §3.2): инвайт-код или открытый режим
 * (APP_OPEN_REGISTRATION). После 201 — автовход ROPC.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { router } from "expo-router";
import { register, registerErrorText } from "../src/services/register-service";
import { theme, useThemedStyles } from "../src/theme";

export default function Register() {
  const [inviteCode, setInviteCode] = useState("");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const styles = useStyles();

  const submit = async () => {
    if (!username.trim() || !password) {
      setError("Заполните логин и пароль");
      return;
    }
    if (password.length < 8) {
      setError("Пароль — минимум 8 символов");
      return;
    }
    if (password !== password2) {
      setError("Пароли не совпадают");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await register({
        username: username.trim(),
        password,
        inviteCode: inviteCode.trim() || undefined,
        displayName: displayName.trim() || undefined,
      });
      router.replace("/(app)/chats");
    } catch (e) {
      setError(registerErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "android" ? undefined : "padding"}>
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>Регистрация</Text>

        <TextInput
          style={styles.input}
          placeholder="Инвайт-код (если есть)"
          autoCapitalize="none"
          autoCorrect={false}
          value={inviteCode}
          onChangeText={setInviteCode}
          editable={!busy}
        />
        <TextInput
          style={styles.input}
          placeholder="Логин (мин. 3 символа)"
          autoCapitalize="none"
          autoCorrect={false}
          value={username}
          onChangeText={setUsername}
          editable={!busy}
        />
        <TextInput
          style={styles.input}
          placeholder="Отображаемое имя (необязательно)"
          value={displayName}
          onChangeText={setDisplayName}
          editable={!busy}
        />
        <TextInput
          style={styles.input}
          placeholder="Пароль (мин. 8 символов)"
          secureTextEntry
          value={password}
          onChangeText={setPassword}
          editable={!busy}
        />
        <TextInput
          style={styles.input}
          placeholder="Пароль ещё раз"
          secureTextEntry
          value={password2}
          onChangeText={setPassword2}
          editable={!busy}
        />

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <Pressable style={[styles.button, busy && styles.buttonDisabled]} onPress={submit} disabled={busy}>
          {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Создать аккаунт</Text>}
        </Pressable>

        <Pressable onPress={() => router.back()} disabled={busy}>
          <Text style={styles.link}>У меня уже есть аккаунт</Text>
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const useStyles = () => useThemedStyles(() => StyleSheet.create({
  flex: { flex: 1, backgroundColor: theme.colors.background },
  container: { flexGrow: 1, justifyContent: "center", padding: 24, gap: 12 },
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
