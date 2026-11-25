/**
 * Инфо о чате (§12): участники + роли; управление — как в вебе (GroupInfoDialog):
 * переименование (owner/admin), добавление участников поиском (admin/owner,
 * идемпотентно), исключение (admin — member'ов; owner — кроме owner), смена роли
 * member↔admin (owner), передача владения (owner), удаление чата (owner),
 * выход из чата (leave = remove_member себя). Для direct — только состав.
 */

import { Alert, FlatList, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useMemo, useState } from "react";
import { router, useLocalSearchParams } from "expo-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { chatsApi, usersApi } from "../../../../src/api/endpoints";
import { queryKeys } from "../../../../src/api/query-keys";
import { useSession } from "../../../../src/stores/session";
import { useDebounced } from "../../../../src/hooks/use-debounced";
import { t } from "../../../../src/i18n/ru";
import { theme, useThemedStyles } from "../../../../src/theme";
import type { ChatMember, MemberRole } from "../../../../src/api/types";

function MemberRow({
  member,
  meId,
  isOwner,
  isAdmin,
  onRemove,
  onRoleChange,
  onTransfer,
}: {
  member: ChatMember;
  meId: string | null;
  isOwner: boolean;
  isAdmin: boolean;
  onRemove: (m: ChatMember) => void;
  onRoleChange: (m: ChatMember, role: MemberRole) => void;
  onTransfer: (m: ChatMember) => void;
}) {
  const styles = useStyles();
  const roleLabel = t(`info.role.${member.role}` as const);
  // Полномочия над участником — как в вебе (canModerate): owner — над всеми кроме
  // себя; admin — только над member. Owner'a не трогает никто.
  const moddable =
    member.role !== "owner" && member.user_id !== meId && (isOwner || (isAdmin && member.role === "member"));
  const roleMutable = isOwner && member.user_id !== meId && member.role !== "owner";
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
      <View style={styles.rowActions}>
        {member.role === "owner" ? <Text style={styles.crown}>👑</Text> : null}
        <Text style={styles.role}>{roleLabel}</Text>
        {roleMutable ? (
          <Pressable
            style={styles.iconBtn}
            accessibilityLabel={t("info.roleChange", { name: member.user.display_name })}
            onPress={() =>
              Alert.alert(t("info.roleChange", { name: member.user.display_name }), undefined, [
                { text: t("common.cancel"), style: "cancel" },
                {
                  text: t("info.roleAdminOption"),
                  onPress: () => onRoleChange(member, "admin"),
                },
                {
                  text: t("info.roleMemberOption"),
                  onPress: () => onRoleChange(member, "member"),
                },
              ])
            }
          >
            <Text style={styles.iconText}>🛡</Text>
          </Pressable>
        ) : null}
        {moddable ? (
          <>
            <Pressable
              style={styles.iconBtn}
              accessibilityLabel={t("info.removeConfirm", { name: member.user.display_name })}
              onPress={() => onRemove(member)}
            >
              <Text style={[styles.iconText, styles.dangerText]}>✕</Text>
            </Pressable>
            {isOwner ? (
              <Pressable style={styles.iconBtn} accessibilityLabel={t("info.transfer")} onPress={() => onTransfer(member)}>
                <Text style={styles.iconText}>👑</Text>
              </Pressable>
            ) : null}
          </>
        ) : null}
      </View>
    </View>
  );
}

export default function ChatInfoScreen() {
  const styles = useStyles();
  const { id: chatId } = useLocalSearchParams<{ id: string }>();
  const meId = useSession((s) => s.user?.id ?? null);
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: queryKeys.chats.detail(chatId),
    queryFn: () => chatsApi.get(chatId),
  });
  const [title, setTitle] = useState<string | null>(null);

  // Добавление участников: инлайн-блок поиска (как в вебе) — admin/owner
  const [adding, setAdding] = useState(false);
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebounced(query.trim(), 400);
  const users = useQuery({
    queryKey: queryKeys.users.search(debouncedQuery),
    queryFn: () => usersApi.search(debouncedQuery),
    enabled: adding && debouncedQuery.length >= 2,
    staleTime: 10_000,
  });

  const myRole = detail.data?.members.find((m) => m.user_id === meId)?.role;
  const isOwner = myRole === "owner";
  const isAdmin = myRole === "owner" || myRole === "admin";
  const canManage = detail.data?.type === "group" && isAdmin;

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

  const addMembers = useMutation({
    mutationFn: (userId: string) => chatsApi.addMembers(chatId, [userId]),
    onSuccess: invalidate,
  });

  const removeMember = useMutation({
    mutationFn: (userId: string) => chatsApi.removeMember(chatId, userId),
    onSuccess: invalidate,
  });

  const setRole = useMutation({
    mutationFn: (p: { userId: string; role: MemberRole }) => chatsApi.setRole(chatId, p.userId, p.role),
    onSuccess: invalidate,
  });

  const transferOwner = useMutation({
    mutationFn: (userId: string) => chatsApi.transferOwner(chatId, userId),
    onSuccess: invalidate,
  });

  const deleteChat = useMutation({
    mutationFn: () => chatsApi.deleteChat(chatId),
    onSuccess: () => {
      invalidate();
      router.replace("/chats");
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

  const onRemove = (m: ChatMember) => {
    Alert.alert(t("info.removeConfirm", { name: m.user.display_name }), undefined, [
      { text: t("common.cancel"), style: "cancel" },
      { text: t("info.remove"), style: "destructive", onPress: () => removeMember.mutate(m.user_id) },
    ]);
  };

  const onTransfer = (m: ChatMember) => {
    Alert.alert(t("info.transferConfirm", { name: m.user.display_name }), undefined, [
      { text: t("common.cancel"), style: "cancel" },
      { text: t("info.transfer"), onPress: () => transferOwner.mutate(m.user_id) },
    ]);
  };

  const onDelete = () => {
    Alert.alert(t("info.deleteConfirm"), undefined, [
      { text: t("common.cancel"), style: "cancel" },
      { text: t("info.delete"), style: "destructive", onPress: () => deleteChat.mutate() },
    ]);
  };

  // Кандидаты в участники: все найденные, кроме уже состоящих (боты разрешены — §12)
  const existingIds = useMemo(() => new Set((detail.data?.members ?? []).map((m) => m.user_id)), [detail.data]);
  const candidates = useMemo(
    () => (users.data ?? []).filter((u) => !existingIds.has(u.id)),
    [users.data, existingIds],
  );

  const chat = detail.data;
  const showFooter = chat?.type === "group";

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
        renderItem={({ item }) => (
          <MemberRow
            member={item}
            meId={meId}
            isOwner={isOwner}
            isAdmin={isAdmin}
            onRemove={onRemove}
            onRoleChange={(m, role) => setRole.mutate({ userId: m.user_id, role })}
            onTransfer={onTransfer}
          />
        )}
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
            <View style={styles.membersHeaderRow}>
              <Text style={styles.membersHeader}>
                {t("info.members", { count: chat?.members.length ?? 0 })}
              </Text>
              {canManage ? (
                <Pressable
                  style={styles.addBtn}
                  onPress={() => {
                    setQuery("");
                    setAdding((v) => !v);
                  }}
                >
                  <Text style={styles.addBtnText}>{t("info.add")}</Text>
                </Pressable>
              ) : null}
            </View>
            {adding ? (
              <View style={styles.addBlock}>
                <TextInput
                  style={styles.searchInput}
                  value={query}
                  onChangeText={setQuery}
                  placeholder={t("info.searchPlaceholder")}
                  placeholderTextColor={theme.colors.textSecondary}
                />
                {debouncedQuery.length >= 2
                  ? candidates.map((u) => (
                      <Pressable
                        key={u.id}
                        style={styles.candidateRow}
                        disabled={addMembers.isPending}
                        onPress={() => addMembers.mutate(u.id)}
                      >
                        <View style={styles.avatar}>
                          <Text style={styles.avatarText}>{u.display_name.slice(0, 1).toUpperCase()}</Text>
                        </View>
                        <View style={styles.rowCenter}>
                          <Text style={styles.rowTitle} numberOfLines={1}>
                            {u.display_name}
                          </Text>
                          <Text style={styles.rowSubtitle}>
                            @{u.username}
                            {u.is_bot ? ` · ${t("info.bot")}` : ""}
                          </Text>
                        </View>
                        <Text style={styles.plus}>＋</Text>
                      </Pressable>
                    ))
                  : null}
                {debouncedQuery.length >= 2 && users.isSuccess && candidates.length === 0 ? (
                  <Text style={styles.noUsers}>{t("info.noUsers")}</Text>
                ) : null}
              </View>
            ) : null}
          </>
        }
        ListFooterComponent={
          showFooter ? (
            <>
              {isOwner ? (
                <Pressable style={styles.deleteBtn} onPress={onDelete} disabled={deleteChat.isPending}>
                  <Text style={styles.leaveText}>{t("info.deleteChat")}</Text>
                </Pressable>
              ) : null}
              {myRole !== "owner" ? (
                <Pressable style={styles.leaveBtn} onPress={onLeave} disabled={leave.isPending}>
                  <Text style={styles.leaveText}>{t("info.leave")}</Text>
                </Pressable>
              ) : null}
            </>
          ) : null
        }
        style={styles.list}
      />
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
  membersHeaderRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: theme.spacing.lg,
    paddingTop: theme.spacing.md,
    paddingBottom: theme.spacing.xs,
  },
  membersHeader: {
    fontSize: theme.font.sm,
    color: theme.colors.textSecondary,
  },
  addBtn: {
    borderWidth: 1,
    borderColor: theme.colors.primary,
    borderRadius: theme.radius.sm,
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 4,
  },
  addBtnText: { fontSize: theme.font.sm, color: theme.colors.primary, fontWeight: "500" },
  addBlock: {
    paddingHorizontal: theme.spacing.lg,
    paddingBottom: theme.spacing.sm,
  },
  searchInput: {
    borderWidth: 1,
    borderColor: theme.colors.border,
    borderRadius: theme.radius.sm,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: 8,
    fontSize: theme.font.md,
    color: theme.colors.text,
    marginBottom: theme.spacing.xs,
  },
  candidateRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: theme.spacing.sm,
    paddingVertical: 8,
  },
  plus: { fontSize: 18, color: theme.colors.primary },
  noUsers: {
    fontSize: theme.font.sm,
    color: theme.colors.textSecondary,
    paddingVertical: theme.spacing.sm,
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
  rowActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  role: { fontSize: theme.font.sm, color: theme.colors.textSecondary, marginRight: 2 },
  crown: { fontSize: 13 },
  iconBtn: {
    width: 28,
    height: 28,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: theme.radius.sm,
  },
  iconText: { fontSize: 15, color: theme.colors.textSecondary },
  dangerText: { color: theme.colors.danger },
  deleteBtn: {
    borderWidth: 1,
    borderColor: theme.colors.danger,
    borderRadius: theme.radius.sm,
    alignItems: "center",
    paddingVertical: 12,
    marginHorizontal: theme.spacing.lg,
    marginTop: theme.spacing.lg,
    marginBottom: theme.spacing.sm,
  },
  leaveBtn: {
    borderWidth: 1,
    borderColor: theme.colors.danger,
    borderRadius: theme.radius.sm,
    alignItems: "center",
    paddingVertical: 12,
    marginHorizontal: theme.spacing.lg,
    marginTop: theme.spacing.sm,
    marginBottom: theme.spacing.lg,
  },
  leaveText: { color: theme.colors.danger, fontSize: theme.font.md, fontWeight: "500" },
}));
