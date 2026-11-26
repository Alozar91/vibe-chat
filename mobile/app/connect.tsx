/**
 * Онбординг: подключение к серверу (Docs/concept.md §19.3, Docs/android.md §3.13).
 * Первый экран приложения, пока профиль сервера не выбран: адрес + опциональное
 * кодовое слово → GET /server/info → сохранение профиля → дальше gate/логин.
 * Успех сигнализируем через onStart() — рут (_layout) переключится на Stack.
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
} from "react-native";
import { theme, useThemedStyles } from "../src/theme";
import { t } from "../src/i18n/ru";
import { ConnectError, connectServer, type ServerProfile } from "../src/services/server-profile";

interface Props {
  onStart: (profile: ServerProfile) => void;
}

export default function Connect({ onStart }: Props) {
  const styles = useStyles();
  const [url, setUrl] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      const profile = await connectServer(url, code);
      onStart(profile);
    } catch (e) {
      setError(e instanceof ConnectError ? e.message : "Не удалось подключиться");
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "android" ? undefined : "padding"}
    >
      <Text style={styles.title}>Vibe Chat</Text>
      <Text style={styles.subtitle}>{t("connect.subtitle")}</Text>

      <TextInput
        style={styles.input}
        placeholder={t("connect.urlPlaceholder")}
        placeholderTextColor={theme.colors.textSecondary}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        value={url}
        onChangeText={setUrl}
        testID="connect-url"
      />
      <TextInput
        style={styles.input}
        placeholder={t("connect.codePlaceholder")}
        placeholderTextColor={theme.colors.textSecondary}
        autoCapitalize="none"
        autoCorrect={false}
        value={code}
        onChangeText={setCode}
        testID="connect-code"
      />

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <Pressable style={[styles.button, busy && styles.buttonDisabled]} onPress={() => void submit()}>
        {busy ? (
          <ActivityIndicator color={theme.colors.primaryText} />
        ) : (
          <Text style={styles.buttonText}>{t("connect.submit")}</Text>
        )}
      </Pressable>

      {__DEV__ ? <Text style={styles.devHint}>{t("connect.devHint")}</Text> : null}
    </KeyboardAvoidingView>
  );
}

const useStyles = () =>
  useThemedStyles(() =>
    StyleSheet.create({
      container: {
        flex: 1,
        justifyContent: "center",
        padding: theme.spacing.xl,
        gap: theme.spacing.md,
        backgroundColor: theme.colors.background,
      },
      title: {
        fontSize: 28,
        fontWeight: "700",
        color: theme.colors.text,
        textAlign: "center",
      },
      subtitle: {
        fontSize: theme.font.md,
        color: theme.colors.textSecondary,
        textAlign: "center",
        marginBottom: theme.spacing.xl,
      },
      input: {
        borderWidth: 1,
        borderColor: theme.colors.border,
        borderRadius: theme.radius.md,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.sm + 2,
        fontSize: theme.font.md,
        color: theme.colors.text,
        backgroundColor: theme.colors.surface,
      },
      error: {
        fontSize: theme.font.sm,
        color: theme.colors.danger,
        textAlign: "center",
      },
      button: {
        backgroundColor: theme.colors.primary,
        borderRadius: theme.radius.md,
        paddingVertical: theme.spacing.sm + 4,
        alignItems: "center",
        marginTop: theme.spacing.sm,
      },
      buttonDisabled: { opacity: 0.6 },
      buttonText: {
        color: theme.colors.primaryText,
        fontSize: theme.font.md,
        fontWeight: "700",
      },
      devHint: {
        fontSize: theme.font.sm,
        color: theme.colors.textSecondary,
        textAlign: "center",
        marginTop: theme.spacing.lg,
      },
    })
  );
