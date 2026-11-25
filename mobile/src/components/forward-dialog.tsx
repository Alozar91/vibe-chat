/**
 * Диалог пересылки (§6): мультивыбор чатов (кроме исходного) →
 * POST /messages/{id}/forward. Вложения копируются на сервере;
 * кэш целевых лент не трогаем — догрузятся при открытии.
 */

import { FlatList, Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { chatsApi, messagesApi } from "../api/endpoints";
import { useChatDetail } from "../hooks/use-chats";
import { useSession } from "../stores/session";
import { t } from "../i18n/ru";
import { theme } from "../theme";
import type { Chat, Message } from "../api/types";

/** Заголовок чата в диалоге (как ChatListItem: direct → имя собеседника). */
function ChatRow({
  chat,
  meId,
  selected,
  onToggle,
}: {
  chat: Chat;
  meId: string | null;
  selected: boolean;
  onToggle: () => void;
}) {
  const detail = useChatDetail(chat.id);
  const title =
    chat.type === "group"
      ? chat.title ?? t("chats.title")
      : detail.data?.members.find((m) => m.user_id !== meId)?.user.display_name ?? "…";
  return (
    <Pressable style={[styles.row, selected && styles.rowSelected]} onPress={onToggle}>
      <View style={styles.avatar}>
        <Text style={styles.avatarText}>{title.slice(0, 1).toUpperCase()}</Text>
      </View>
      <Text style={styles.rowTitle} numberOfLines={1}>
        {title}
        {chat.type === "group" ? ` · ${t("forward.groupTag")}` : ""}
      </Text>
      {selected ? <Text style={styles.check}>✓</Text> : null}
    </Pressable>
  );
}

export function ForwardDialog({ message, onClose }: { message: Message; onClose: () => void }) {
  const meId = useSession((s) => s.user?.id ?? null);
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string[]>([]);

  const chats = useQuery({ queryKey: ["chats"], queryFn: chatsApi.list });
  const candidates = (chats.data ?? []).filter((c) => c.id !== message.chat_id);

  const forward = useMutation({
    mutationFn: () => messagesApi.forward(message.id, selected),
    onSuccess: () => {
      // у целевых чатов обновится last_message_at
      void queryClient.invalidateQueries({ queryKey: ["chats"] });
      onClose();
    },
  });

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]));

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose}>
        <Pressable style={styles.dialog}>
          <Text style={styles.title}>{t("forward.title")}</Text>
          <Text style={styles.preview} numberOfLines={1}>
            {message.text ?? "…"}
          </Text>
          <FlatList
            data={candidates}
            keyExtractor={(c) => c.id}
            style={styles.list}
            renderItem={({ item }) => (
              <ChatRow
                chat={item}
                meId={meId}
                selected={selected.includes(item.id)}
                onToggle={() => toggle(item.id)}
              />
            )}
            ListEmptyComponent={
              chats.isLoading ? null : <Text style={styles.empty}>{t("forward.noChats")}</Text>
            }
          />
          <Pressable
            style={[styles.sendBtn, (selected.length === 0 || forward.isPending) && styles.sendBtnDisabled]}
            disabled={selected.length === 0 || forward.isPending}
            onPress={() => forward.mutate()}
          >
            <Text style={styles.sendBtnText}>
              {forward.isPending ? t("forward.sending") : t("forward.send")}
            </Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "center" },
  dialog: {
    alignSelf: "center",
    width: "86%",
    maxHeight: "70%",
    backgroundColor: theme.colors.background,
    borderRadius: theme.radius.lg,
    padding: theme.spacing.lg,
  },
  title: { fontSize: theme.font.lg, fontWeight: "600", color: theme.colors.text },
  preview: {
    color: theme.colors.textSecondary,
    fontSize: theme.font.sm,
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.sm,
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 6,
    marginVertical: theme.spacing.sm,
  },
  list: { flexGrow: 0, marginVertical: theme.spacing.xs },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: theme.spacing.sm,
    paddingHorizontal: theme.spacing.xs,
    paddingVertical: 8,
    borderRadius: theme.radius.sm,
  },
  rowSelected: { backgroundColor: "rgba(37,99,235,0.08)" },
  avatar: {
    width: 32,
    height: 32,
    borderRadius: theme.radius.full,
    backgroundColor: theme.colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: { color: theme.colors.primaryText, fontSize: theme.font.sm, fontWeight: "600" },
  rowTitle: { flex: 1, fontSize: theme.font.md, color: theme.colors.text },
  check: { color: theme.colors.primary, fontSize: theme.font.md },
  empty: {
    textAlign: "center",
    color: theme.colors.textSecondary,
    paddingVertical: theme.spacing.md,
    fontSize: theme.font.sm,
  },
  sendBtn: {
    backgroundColor: theme.colors.primary,
    borderRadius: theme.radius.sm,
    alignItems: "center",
    paddingVertical: 10,
    marginTop: theme.spacing.sm,
  },
  sendBtnDisabled: { opacity: 0.4 },
  sendBtnText: { color: theme.colors.primaryText, fontSize: theme.font.md, fontWeight: "500" },
});
