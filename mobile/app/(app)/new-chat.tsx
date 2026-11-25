/**
 * Новый чат (§12): таб «Личный» — поиск пользователей (debounce) →
 * POST /chats/direct (идемпотентно: существующий вернётся с created=false);
 * таб «Группа» — название + мультивыбор участников → POST /chats.
 */

import { FlatList, Modal, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useEffect, useMemo, useState } from "react";
import { router } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { chatsApi, usersApi } from "../../src/api/endpoints";
import { queryKeys } from "../../src/api/query-keys";
import { useSession } from "../../src/stores/session";
import { useDebounced } from "../../src/hooks/use-debounced";
import { t } from "../../src/i18n/ru";
import { theme, useThemedStyles } from "../../src/theme";
import type { User } from "../../src/api/types";

function UserRow({
  user,
  selected,
  onPress,
}: {
  user: User;
  selected?: boolean;
  onPress: () => void;
}) {
  const styles = useStyles();
  return (
    <Pressable style={[styles.row, selected && styles.rowSelected]} onPress={onPress}>
      <View style={styles.avatar}>
        <Text style={styles.avatarText}>{user.display_name.slice(0, 1).toUpperCase()}</Text>
      </View>
      <View style={styles.rowCenter}>
        <Text style={styles.rowTitle} numberOfLines={1}>
          {user.display_name}
        </Text>
        <Text style={styles.rowSubtitle}>@{user.username}</Text>
      </View>
      {selected ? <Text style={styles.check}>✓</Text> : null}
    </Pressable>
  );
}

export default function NewChatScreen() {
  const styles = useStyles();
  const meId = useSession((s) => s.user?.id ?? null);
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"direct" | "group">("direct");
  const [query, setQuery] = useState("");
  const [groupTitle, setGroupTitle] = useState("");
  const [memberIds, setMemberIds] = useState<string[]>([]);

  // debounce — не спамить поиск на каждый символ (§16 лимиты)
  const debouncedQuery = useDebounced(query.trim(), 400);
  const users = useQuery({
    queryKey: queryKeys.users.search(debouncedQuery),
    queryFn: () => usersApi.search(debouncedQuery),
    enabled: debouncedQuery.length >= 2,
    staleTime: 10_000,
  });

  const direct = useMutation({
    mutationFn: (userId: string) => chatsApi.createDirect(userId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.chats.all() });
      router.replace("/chats");
    },
  });

  const createGroup = useMutation({
    mutationFn: () => chatsApi.createGroup(groupTitle.trim(), memberIds),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.chats.all() });
      router.replace("/chats");
    },
  });

  const list = useMemo(
    () => (users.data ?? []).filter((u) => u.id !== meId && !u.is_bot),
    [users.data, meId],
  );

  const toggleMember = (id: string) =>
    setMemberIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const busy = direct.isPending || createGroup.isPending;

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.back}>
          <Text style={styles.backText}>‹</Text>
        </Pressable>
        <Text style={styles.headerTitle}>{t("newChat.title")}</Text>
      </View>

      <View style={styles.tabs}>
        {(["direct", "group"] as const).map((mode) => (
          <Pressable
            key={mode}
            style={[styles.tab, tab === mode && styles.tabActive]}
            onPress={() => setTab(mode)}
          >
            <Text style={[styles.tabText, tab === mode && styles.tabTextActive]}>
              {t(mode === "direct" ? "newChat.tabDirect" : "newChat.tabGroup")}
            </Text>
          </Pressable>
        ))}
      </View>

      {tab === "group" ? (
        <TextInput
          style={styles.groupTitle}
          value={groupTitle}
          onChangeText={setGroupTitle}
          placeholder={t("newChat.groupTitlePlaceholder")}
          placeholderTextColor={theme.colors.textSecondary}
        />
      ) : null}

      <TextInput
        style={styles.search}
        value={query}
        onChangeText={setQuery}
        placeholder={t("newChat.searchPlaceholder")}
        placeholderTextColor={theme.colors.textSecondary}
        autoCapitalize="none"
      />

      {tab === "group" && memberIds.length > 0 ? (
        <Text style={styles.selected}>
          {t("newChat.selected", { count: memberIds.length })}
        </Text>
      ) : null}

      <FlatList
        data={list}
        keyExtractor={(u) => u.id}
        renderItem={({ item }) => (
          <UserRow
            user={item}
            selected={tab === "group" && memberIds.includes(item.id)}
            onPress={() => {
              if (tab === "group") {
                toggleMember(item.id);
              } else if (!busy) {
                direct.mutate(item.id);
              }
            }}
          />
        )}
        ListEmptyComponent={
          debouncedQuery.length >= 2 && !users.isLoading ? (
            <Text style={styles.empty}>{t("newChat.empty")}</Text>
          ) : null
        }
        style={styles.list}
      />

      {tab === "group" ? (
        <Pressable
          style={[styles.createBtn, (memberIds.length === 0 || !groupTitle.trim() || busy) && styles.btnDisabled]}
          disabled={memberIds.length === 0 || !groupTitle.trim() || busy}
          onPress={() => createGroup.mutate()}
        >
          <Text style={styles.createBtnText}>
            {createGroup.isPending ? t("newChat.creating") : t("newChat.create")}
          </Text>
        </Pressable>
      ) : null}
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
  tabs: {
    flexDirection: "row",
    paddingHorizontal: theme.spacing.md,
    paddingTop: theme.spacing.sm,
    gap: theme.spacing.sm,
  },
  tab: {
    flex: 1,
    alignItems: "center",
    paddingVertical: 8,
    borderRadius: theme.radius.sm,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  tabActive: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
  tabText: { fontSize: theme.font.md, color: theme.colors.text },
  tabTextActive: { color: theme.colors.primaryText, fontWeight: "500" },
  groupTitle: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.sm,
    marginHorizontal: theme.spacing.md,
    marginTop: theme.spacing.sm,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: 10,
    fontSize: theme.font.md,
    color: theme.colors.text,
  },
  search: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.sm,
    marginHorizontal: theme.spacing.md,
    marginTop: theme.spacing.sm,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: 10,
    fontSize: theme.font.md,
    color: theme.colors.text,
  },
  selected: {
    paddingHorizontal: theme.spacing.lg,
    paddingTop: theme.spacing.sm,
    fontSize: theme.font.sm,
    color: theme.colors.textSecondary,
  },
  list: { flex: 1, marginTop: theme.spacing.xs },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: theme.spacing.sm,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: 8,
  },
  rowSelected: { backgroundColor: "rgba(37,99,235,0.08)" },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: theme.radius.full,
    backgroundColor: theme.colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: { color: theme.colors.primaryText, fontSize: theme.font.sm, fontWeight: "600" },
  rowCenter: { flex: 1 },
  rowTitle: { fontSize: theme.font.md, color: theme.colors.text },
  rowSubtitle: { fontSize: theme.font.sm, color: theme.colors.textSecondary },
  check: { color: theme.colors.primary, fontSize: theme.font.lg },
  empty: {
    textAlign: "center",
    color: theme.colors.textSecondary,
    paddingVertical: theme.spacing.lg,
    fontSize: theme.font.sm,
  },
  createBtn: {
    backgroundColor: theme.colors.primary,
    borderRadius: theme.radius.sm,
    alignItems: "center",
    paddingVertical: 12,
    margin: theme.spacing.md,
  },
  btnDisabled: { opacity: 0.4 },
  createBtnText: { color: theme.colors.primaryText, fontSize: theme.font.md, fontWeight: "500" },
}));
