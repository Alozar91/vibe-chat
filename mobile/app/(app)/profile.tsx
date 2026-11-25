/**
 * Профиль (§5): персональные данные — в PostgreSQL системы, редактируются
 * через PATCH /users/me (username — неизменяемый идентификатор из KC).
 * time_display/timezone — режим отображения времени сообщений.
 * Кнопка «Выйти» — logout (§3.2): revoke refresh, чистка токенов и кэша.
 */

import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useEffect, useState } from "react";
import { router } from "expo-router";
import { usersApi } from "../../src/api/endpoints";
import { logout } from "../../src/services/session-service";
import { notificationsEnabled, openNotificationSettings } from "../../src/services/push-service";
import {
  getServerProfile,
  serverDisplayName,
  useServerProfile,
  wsSchemeFor,
} from "../../src/services/server-profile";
import { useSession } from "../../src/stores/session";
import { t } from "../../src/i18n/ru";
import { theme, useThemedStyles } from "../../src/theme";
import type { TimeDisplay } from "../../src/api/types";
import { InviteAdminSection } from "../../src/components/invite-admin-section";
import { applyTheme, useThemeStore, type ThemeMode } from "../../src/theme";

const TIME_DISPLAYS: TimeDisplay[] = ["browser", "as_sent", "fixed", "utc"];
const THEME_MODES: ThemeMode[] = ["light", "dark", "system"];
const THEME_KEY = { light: "light", dark: "dark", system: "system" } as const;

export default function ProfileScreen() {
  const styles = useStyles();
  const themeMode = useThemeStore((s) => s.mode);
  const sessionUser = useSession((s) => s.user);
  const [displayName, setDisplayName] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [timeDisplay, setTimeDisplay] = useState<TimeDisplay>("browser");
  const [timezone, setTimezone] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [notifEnabled, setNotifEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    void notificationsEnabled().then(setNotifEnabled);

    usersApi
      .me()
      .then((u) => {
        setDisplayName(u.display_name);
        setFirstName(u.first_name ?? "");
        setLastName(u.last_name ?? "");
        setEmail(u.email ?? "");
        setTimeDisplay(u.time_display);
        setTimezone(u.timezone ?? "");
        setIsAdmin(u.is_platform_admin);
      })
      .catch(() => setError(t("common.unknownError")))
      .finally(() => setLoading(false));
  }, []);

  const onSave = async () => {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const u = await usersApi.updateMe({
        display_name: displayName.trim(),
        first_name: firstName.trim() || null,
        last_name: lastName.trim() || null,
        email: email.trim() || null,
        time_display: timeDisplay,
        timezone: timeDisplay === "fixed" ? timezone.trim() || null : null,
      });
      // session-шапка (список чатов) показывает display_name — синхронизируем
      useSession.getState().setUser(
        sessionUser ? { ...sessionUser, display_name: u.display_name } : sessionUser,
      );
      setSaved(true);
    } catch (e) {
      const msg = e instanceof Error ? e.message : t("common.unknownError");
      setError(msg + (String(e).includes("422") ? ` (${t("profile.timezone")})` : ""));
    } finally {
      setSaving(false);
    }
  };

  const onLogout = () => {
    Alert.alert(t("profile.logoutConfirm"), undefined, [
      { text: t("common.cancel"), style: "cancel" },
      {
        text: t("profile.logout"),
        style: "destructive",
        onPress: () => {
          void logout().finally(() => router.replace("/login"));
        },
      },
    ]);
  };

  const profile = getServerProfile();
  const serverInfo = profile
    ? `${serverDisplayName(profile)} — ${profile.baseUrl} (${wsSchemeFor(profile.baseUrl)}…/api/v1/ws, пушей: ${profile.push.driver})`
    : "";

  /** Смена сервера (§19.3): logout + чистка профиля → онбординг заново.
   * router.replace("/connect") после очистки: _layout перерисуется (профиль null). */
  const onSwitchServer = () => {
    Alert.alert(t("server.switchConfirmTitle"), t("server.switchConfirmText"), [
      { text: t("server.switchConfirmCancel"), style: "cancel" },
      {
        text: t("server.switchConfirmOk"),
        style: "destructive",
        onPress: () => {
          void logout()
            .catch(() => {})
            .finally(() => {
              // Порядок важен: только снимаем профиль — _layout размонтирует Stack
              // целиком и рендерит Connect; навигацию явно не трогаем (replace
              // без живого навигатора даёт «action REPLACE not handled»).
              useServerProfile.getState().set(null);
            });
        },
      },
    ]);
  };

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.back}>
          <Text style={styles.backText}>‹</Text>
        </Pressable>
        <Text style={styles.headerTitle}>{t("profile.title")}</Text>
      </View>

      {loading ? (
        <ActivityIndicator style={styles.loader} color={theme.colors.primary} />
      ) : (
        <ScrollView contentContainerStyle={styles.body}>
          <Text style={styles.label}>{t("profile.username")}</Text>
          <Text style={[styles.input, styles.disabled]}>@{sessionUser?.username ?? "…"}</Text>

          <Text style={styles.label}>{t("profile.displayName")}</Text>
          <TextInput
            style={styles.input}
            value={displayName}
            onChangeText={setDisplayName}
            placeholder={t("profile.displayName")}
            placeholderTextColor={theme.colors.textSecondary}
          />

          <View style={styles.row}>
            <View style={styles.half}>
              <Text style={styles.label}>{t("profile.firstName")}</Text>
              <TextInput style={styles.input} value={firstName} onChangeText={setFirstName} />
            </View>
            <View style={styles.half}>
              <Text style={styles.label}>{t("profile.lastName")}</Text>
              <TextInput style={styles.input} value={lastName} onChangeText={setLastName} />
            </View>
          </View>

          <Text style={styles.label}>{t("profile.email")}</Text>
          <TextInput
            style={styles.input}
            value={email}
            onChangeText={setEmail}
            keyboardType="email-address"
            autoCapitalize="none"
          />

          <Text style={styles.note}>{t("profile.personalNote")}</Text>

          <Text style={[styles.section, styles.label]}>Время</Text>
          <View style={styles.chips}>
            {TIME_DISPLAYS.map((mode) => (
              <Pressable
                key={mode}
                style={[styles.chip, timeDisplay === mode && styles.chipActive]}
                onPress={() => setTimeDisplay(mode)}
              >
                <Text style={[styles.chipText, timeDisplay === mode && styles.chipTextActive]}>
                  {t(`profile.timeDisplay.${mode === "as_sent" ? "asSent" : mode}` as const)}
                </Text>
              </Pressable>
            ))}
          </View>
          {timeDisplay === "fixed" ? (
            <TextInput
              style={styles.input}
              value={timezone}
              onChangeText={setTimezone}
              placeholder={t("profile.timezone")}
              placeholderTextColor={theme.colors.textSecondary}
              autoCapitalize="none"
            />
          ) : null}

          <Text style={[styles.section, styles.label]}>{t("profile.theme")}</Text>
          <View style={styles.chips}>
            {THEME_MODES.map((mode) => (
              <Pressable
                key={mode}
                style={[styles.chip, themeMode === mode && styles.chipActive]}
                onPress={() => applyTheme(mode)}
              >
                <Text style={[styles.chipText, themeMode === mode && styles.chipTextActive]}>
                  {t(`theme.${THEME_KEY[mode]}` as const)}
                </Text>
              </Pressable>
            ))}
          </View>

          <Pressable style={styles.saveBtn} onPress={() => void onSave()} disabled={saving}>
            <Text style={styles.saveBtnText}>{saving ? t("profile.saving") : t("profile.save")}</Text>
          </Pressable>
          {saved ? <Text style={styles.saved}>{t("profile.saved")}</Text> : null}
          {error ? <Text style={styles.error}>{t("profile.saveError", { error })}</Text> : null}

          {isAdmin ? <InviteAdminSection /> : null}

          <Text style={[styles.section, styles.label]}>{t("profile.notifications")}</Text>
          <Pressable style={styles.notifRow} onPress={() => void openNotificationSettings()}>
            <Text style={styles.notifText}>
              {notifEnabled === false ? t("profile.notificationsOff") : t("profile.notificationsOn")}
            </Text>
          </Pressable>

          <Text style={[styles.section, styles.label]}>{t("server.current")}</Text>
          <View style={styles.serverRow}>
            <Text style={styles.serverText} numberOfLines={1} ellipsizeMode="middle">
              {serverInfo}
            </Text>
          </View>
          <Pressable style={styles.serverSwitchBtn} onPress={onSwitchServer}>
            <Text style={styles.serverSwitchText}>{t("server.switch")}</Text>
          </Pressable>

          <Pressable style={styles.logoutBtn} onPress={onLogout}>
            <Text style={styles.logoutText}>{t("profile.logout")}</Text>
          </Pressable>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const useStyles = () => useThemedStyles(() => StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: theme.spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.border,
  },
  back: { paddingHorizontal: theme.spacing.sm },
  backText: { fontSize: 28, color: theme.colors.primary },
  headerTitle: { fontSize: theme.font.lg, fontWeight: "600", color: theme.colors.text },
  loader: { marginTop: theme.spacing.xl },
  body: { padding: theme.spacing.lg },
  row: { flexDirection: "row", gap: theme.spacing.sm },
  half: { flex: 1 },
  label: { fontSize: theme.font.sm, color: theme.colors.textSecondary, marginBottom: 4 },
  section: { marginTop: theme.spacing.lg },
  input: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.sm,
    backgroundColor: theme.colors.surface,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: 10,
    fontSize: theme.font.md,
    color: theme.colors.text,
    marginBottom: theme.spacing.md,
  },
  disabled: { opacity: 0.5 },
  note: { fontSize: theme.font.sm, color: theme.colors.textSecondary, marginVertical: theme.spacing.xs },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: theme.spacing.xs, marginBottom: theme.spacing.sm },
  chip: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.full,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: 6,
  },
  chipActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  chipText: { fontSize: theme.font.sm, color: theme.colors.text },
  chipTextActive: { color: theme.colors.primaryText },
  saveBtn: {
    backgroundColor: theme.colors.primary,
    borderRadius: theme.radius.sm,
    alignItems: "center",
    paddingVertical: 12,
    marginTop: theme.spacing.md,
  },
  saveBtnText: { color: theme.colors.primaryText, fontSize: theme.font.md, fontWeight: "500" },
  saved: { color: theme.colors.accentGreen, fontSize: theme.font.sm, marginTop: theme.spacing.sm },
  error: { color: theme.colors.danger, fontSize: theme.font.sm, marginTop: theme.spacing.sm },
  notifRow: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.sm,
    paddingVertical: 12,
    paddingHorizontal: theme.spacing.md,
    marginBottom: theme.spacing.md,
  },
  notifText: { fontSize: theme.font.md, color: theme.colors.text },
  serverRow: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.sm,
    paddingVertical: 12,
    paddingHorizontal: theme.spacing.md,
    marginBottom: theme.spacing.sm,
  },
  serverText: { fontSize: theme.font.sm, color: theme.colors.text },
  serverSwitchBtn: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.sm,
    alignItems: "center",
    paddingVertical: 12,
    marginBottom: theme.spacing.md,
  },
  serverSwitchText: { color: theme.colors.text, fontSize: theme.font.md },
  logoutBtn: {
    borderWidth: 1,
    borderColor: theme.colors.danger,
    borderRadius: theme.radius.sm,
    alignItems: "center",
    paddingVertical: 12,
    marginTop: theme.spacing.xl,
  },
  logoutText: { color: theme.colors.danger, fontSize: theme.font.md, fontWeight: "500" },
}));
