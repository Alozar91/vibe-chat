/**
 * Инфо о чате (§12): участники + роли; для групп — переименование (owner/admin)
 * и выход из чата (leave = remove_member себя). Для direct — только состав.
 */

import { Alert, FlatList, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useState } from "react";
import { router, useLocalSearchParams } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { chatsApi } from "../../../../src/api/endpoints";
import { queryKeys } from "../../../../src/api/query-keys";
import { useSession } from "../../../../src/stores/session";
import { t } from "../../../../src/i18n/ru";
import { theme } from "../../../../src/theme";
import type { ChatMember, MemberRole } from "../../../../src/api/types";

function MemberRow({ member, meId }: { member: ChatMember; meId: string | null }) {
  const roleLabel = t(`info.role.${member.role}` as const);
  return (
    <View style={styles.row}>
      <View style={styles.avatar}>
        <Text style={styles.avatarText}>{member.user.display_name.slice(0, 1).toUpperCase()}</Text>
      </View>
      <View style={styles.rowCenter}>
        <Text style={styles.rowTitle} numberOfLines={1}>
          {member.user.display_name}
          {member.user_id === meId ? ` ${t("info.you")}` : ""}
        </Text>
        <Text style={styles.rowSubtitle}>@{member.user.username}</Text>
      </View>
      <Text style={styles.role}>{roleLabel}</Text>
    </View>
  );
}

export default function ChatInfoScreen() {
  const { id: chatId } = useLocalSearchParams<{ id: string }>();
  const meId = useSession((s) => s.user?.id ?? null);
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: queryKeys.chats.detail(chatId),
    queryFn: () => chatsApi.get(chatId),
  });
  const [title, setTitle] = useState<string | null>(null);

  const myRole = detail.data?.members.find((m) => m.user_id === meId)?.role;
  const canManage = detail.data?.type === "group" && (myRole === "owner" || myRole === "admin");

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.chats.all() });
  };

  const rename = useMutation({
    mutationFn: () => chatsApi.rename(chatId, (title ?? "").trim()),
    onSuccess: () => {
      setTitle(null);
      invalidate();
    },
  });

  const leave = useMutation({
    mutationFn: () => chatsApi.leave(chatId, meId ?? ""),
    onSuccess: () => {
      invalidate();
      router.replace("/chats");
    },
  });

  const onLeave = () => {
    Alert.alert(t("info.leaveConfirm"), undefined, [
      { text: t("common.cancel"), style: "cancel" },
      { text: t("info.leave"), style: "destructive", onPress: () => leave.mutate() },
    ]);
  };

  const chat = detail.data;

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.back}>
          <Text style={styles.backText}>‹</Text>
        </Pressable>
        <Text style={styles.headerTitle}>{t("info.title")}</Text>
      </View>

      <FlatList
        data={chat?.members ?? []}
        keyExtractor={(m) => m.user_id}
        renderItem={({ item }) => <MemberRow member={item} meId={meId} />}
        ListHeaderComponent={
          <>
            {chat?.type === "group" ? (
              <View style={styles.groupBlock}>
                <Text style={styles.groupTitle}>{chat.title ?? "…"}</Text>
                {canManage ? (
                  <>
                    <TextInput
                      style={styles.renameInput}
                      value={title ?? ""}
                      onChangeText={setTitle}
                      placeholder={t("info.renamePlaceholder")}
                      placeholderTextColor={theme.colors.textSecondary}
                    />
                    <Pressable
                      style={[styles.renameBtn, (!title?.trim() || rename.isPending) && styles.btnDisabled]}
                      disabled={!title?.trim() || rename.isPending}
                      onPress={() => rename.mutate()}
                    >
                      <Text style={styles.renameBtnText}>{t("info.rename")}</Text>
                    </Pressable>
                  </>
                ) : null}
              </View>
            ) : (
              <Text style={styles.directHint}>{t("info.directHint")}</Text>
            )}
            <Text style={styles.membersHeader}>
              {t("info.members", { count: chat?.members.length ?? 0 })}
            </Text>
          </>
        }
        ListFooterComponent={
          chat?.type === "group" && myRole !== "owner" ? (
            <Pressable style={styles.leaveBtn} onPress={onLeave} disabled={leave.isPending}>
              <Text style={styles.leaveText}>{t("info.leave")}</Text>
            </Pressable>
          ) : null
        }
        style={styles.list}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
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
  list: { flex: 1 },
  groupBlock: {
    padding: theme.spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.border,
  },
  groupTitle: { fontSize: theme.font.lg, fontWeight: "600", color: theme.colors.text },
  renameInput: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.sm,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: 8,
    fontSize: theme.font.md,
    color: theme.colors.text,
    marginTop: theme.spacing.md,
  },
  renameBtn: {
    backgroundColor: theme.colors.primary,
    borderRadius: theme.radius.sm,
    alignItems: "center",
    paddingVertical: 8,
    marginTop: theme.spacing.sm,
  },
  btnDisabled: { opacity: 0.4 },
  renameBtnText: { color: theme.colors.primaryText, fontSize: theme.font.sm, fontWeight: "500" },
  directHint: {
    padding: theme.spacing.lg,
    fontSize: theme.font.sm,
    color: theme.colors.textSecondary,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.border,
  },
  membersHeader: {
    paddingHorizontal: theme.spacing.lg,
    paddingTop: theme.spacing.md,
    paddingBottom: theme.spacing.xs,
    fontSize: theme.font.sm,
    color: theme.colors.textSecondary,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: theme.spacing.sm,
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: 8,
  },
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
  role: { fontSize: theme.font.sm, color: theme.colors.textSecondary },
  leaveBtn: {
    borderWidth: 1,
    borderColor: theme.colors.danger,
    borderRadius: theme.radius.sm,
    alignItems: "center",
    paddingVertical: 12,
    margin: theme.spacing.lg,
  },
  leaveText: { color: theme.colors.danger, fontSize: theme.font.md, fontWeight: "500" },
});
