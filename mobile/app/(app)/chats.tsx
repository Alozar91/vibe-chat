/**
 * Список чатов (§3.10): FlatList, сортировка по last_message_at, unread-бейдж,
 * имя direct-чата через useChatDetail (ChatOut без участников — §12),
 * presence-точка из realtime-стора, баннер «нет соединения».
 */

import { FlatList, Pressable, StyleSheet, Text, View } from "react-native";
import { router } from "expo-router";
import { useMemo } from "react";
import { useChats, useChatDetail } from "../../src/hooks/use-chats";
import { useSession } from "../../src/stores/session";
import { useRealtime } from "../../src/stores/realtime";
import { theme, useThemedStyles } from "../../src/theme";
import { t } from "../../src/i18n/ru";
import type { Chat } from "../../src/api/types";

/** presence-точка: online из WS (presence), fallback — ничего (§9). */
function PresenceDot({ userId }: { userId: string }) {
  const online = useRealtime((s) => s.online[userId]?.online);
  const styles = useStyles();
  if (!online) return null;
  return <View style={styles.presenceDot} />;
}

/** Заголовок чата: group → title; direct → имя собеседника (детали чата). */
function ChatTitle({ chat, myId }: { chat: Chat; myId: string | null }) {
  const styles = useStyles();
  const detail = useChatDetail(chat.id);
  const title = useMemo(() => {
    if (chat.type === "group") return chat.title ?? t("chats.title");
    const peer = detail.data?.members.find((m) => m.user_id !== myId)?.user;
    return peer?.display_name ?? chat.title ?? "…";
  }, [chat.type, chat.title, detail.data, myId]);
  const peerId = detail.data?.members.find((m) => m.user_id !== myId)?.user_id;
  return (
    <View style={styles.titleRow}>
      <Text style={styles.title} numberOfLines={1}>
        {title}
      </Text>
      {chat.type === "direct" && peerId ? <PresenceDot userId={peerId} /> : null}
    </View>
  );
}

function ChatListItem({ chat, myId }: { chat: Chat; myId: string | null }) {
  const styles = useStyles();
  return (
    <Pressable
      style={({ pressed }) => [styles.row, pressed && { backgroundColor: theme.colors.surfaceActive }]}
      onPress={() => router.push({ pathname: "/chats/[id]", params: { id: chat.id } })}
    >
      <View style={styles.avatar}>
        <Text style={styles.avatarText}>
          {(chat.type === "group" ? chat.title ?? "?" : "?").slice(0, 1).toUpperCase()}
        </Text>
      </View>
      <View style={styles.rowBody}>
        <ChatTitle chat={chat} myId={myId} />
        <Text style={styles.subtitle}>
          {chat.type === "group" ? t("chats.groupSubtitle") : t("chats.directSubtitle")}
        </Text>
      </View>
      {chat.unread_count > 0 ? (
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{chat.unread_count}</Text>
        </View>
      ) : null}
    </Pressable>
  );
}

export default function ChatsScreen() {
  const styles = useStyles();
  const myId = useSession((s) => s.user?.id ?? null);
  const chats = useChats();
  const status = useRealtime((s) => s.status);

  const sorted = useMemo(() => {
    const list = chats.data ? [...chats.data] : [];
    // сортировка по last_message_at (§12: MAX(id) на сервере не выдаётся)
    list.sort((a, b) =>
      (b.last_message_at ?? b.created_at).localeCompare(a.last_message_at ?? a.created_at),
    );
    return list;
  }, [chats.data]);

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>{t("chats.title")}</Text>
        <View style={styles.headerActions}>
          <Pressable onPress={() => router.push("/new-chat")}>
            <Text style={styles.headerActionBig}>{"＋"}</Text>
          </Pressable>
          <Pressable onPress={() => router.push("/profile")}>
            <Text style={styles.headerAction}>{t("chats.profile")}</Text>
          </Pressable>
        </View>
      </View>
      {status === "closed" ? (
        <View style={styles.banner}>
          <Text style={styles.bannerText}>{t("chats.offlineBanner")}</Text>
        </View>
      ) : null}
      {sorted.length === 0 && !chats.isLoading ? (
        <Text style={styles.empty}>{t("chats.empty")}</Text>
      ) : null}
      <FlatListLike chats={sorted} myId={myId} />
    </View>
  );
}

function FlatListLike({ chats, myId }: { chats: Chat[]; myId: string | null }) {
  const styles = useStyles();
  return (
    <FlatList
      data={chats}
      keyExtractor={(c) => c.id}
      renderItem={({ item }) => <ChatListItem chat={item} myId={myId} />}
      ItemSeparatorComponent={() => <View style={styles.separator} />}
    />
  );
}

const useStyles = () => useThemedStyles(() => StyleSheet.create({
  container: { flex: 1, backgroundColor: theme.colors.background },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: theme.colors.border,
  },
  headerTitle: { fontSize: theme.font.xl, fontWeight: "700", color: theme.colors.text },
  headerActions: { flexDirection: "row", alignItems: "center", gap: theme.spacing.md },
  headerAction: { color: theme.colors.primary, fontSize: theme.font.md },
  headerActionBig: { color: theme.colors.primary, fontSize: 24, fontWeight: "400" },
  banner: {
    backgroundColor: theme.colors.errorBg,
    paddingVertical: theme.spacing.xs,
    paddingHorizontal: theme.spacing.lg,
  },
  bannerText: { color: theme.colors.danger, fontSize: theme.font.sm },
  empty: {
    color: theme.colors.textSecondary,
    textAlign: "center",
    marginTop: theme.spacing.xl,
    paddingHorizontal: theme.spacing.lg,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: theme.spacing.lg,
    paddingVertical: theme.spacing.md,
  },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: theme.radius.full,
    backgroundColor: theme.colors.primary,
    alignItems: "center",
    justifyContent: "center",
    marginRight: theme.spacing.md,
  },
  avatarText: { color: theme.colors.primaryText, fontSize: theme.font.lg, fontWeight: "600" },
  rowBody: { flex: 1 },
  titleRow: { flexDirection: "row", alignItems: "center" },
  title: { fontSize: theme.font.md, fontWeight: "600", color: theme.colors.text, flexShrink: 1 },
  presenceDot: {
    width: 8,
    height: 8,
    borderRadius: theme.radius.full,
    backgroundColor: theme.colors.accentGreen,
    marginLeft: theme.spacing.xs,
  },
  subtitle: { color: theme.colors.textSecondary, fontSize: theme.font.sm, marginTop: 2 },
  badge: {
    backgroundColor: theme.colors.badge,
    borderRadius: theme.radius.full,
    minWidth: 22,
    height: 22,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 6,
  },
  badgeText: { color: theme.colors.primaryText, fontSize: theme.font.sm },
  separator: { height: 1, backgroundColor: theme.colors.border },
}));
