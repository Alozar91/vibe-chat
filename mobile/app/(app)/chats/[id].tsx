/**
 * Экран чата (этапы 3–5, §3.10): inverted-лента с догрузкой истории вверх
 * (?before=), composer с отправкой (Idempotency-Key, timezone), статусы
 * sending/sent/error+retry, typing (throttle 2 c), markRead, вложения
 * (Photo Picker, прогресс, отмена, лимит 100 МБ до PUT), контекстное меню
 * по long-tap (реакции/ответить/удалить).
 */
import { Alert, FlatList, Modal, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { router, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as ImagePicker from "expo-image-picker";
import { MessageBubble, ImageViewer } from "../../../src/components/message-bubble";
import { ForwardDialog } from "../../../src/components/forward-dialog";
import { useChatDetail, useMarkRead, useMessages } from "../../../src/hooks/use-chats";
import { useSendMessage } from "../../../src/hooks/use-send-message";
import { randomUUID } from "../../../src/services/uuid";
import { messagesApi } from "../../../src/api/endpoints";
import { useSession } from "../../../src/stores/session";
import { useRealtime } from "../../../src/stores/realtime";
import { wsClient } from "../../../src/services/ws-client";
import { setActiveChatId } from "../../../src/services/push-service";
import {
  FileTooLargeError,
  type UploadHandle,
  uploadFile,
} from "../../../src/services/upload";
import { t } from "../../../src/i18n/ru";
import { theme } from "../../../src/theme";
import type { Attachment, Message } from "../../../src/api/types";

/** Локальное вложение композера: загрузка в Silo до отправки сообщения. */
interface PendingAttachment {
  fileName: string;
  localUri: string;
  kind: "image" | "video" | "file";
  progress: number;
  handle: UploadHandle | null;
  ready: null | { file_id: string; kind: "image" | "video" | "file" };
  error: string | null;
}

export default function ChatScreen() {
  const { id: chatId } = useLocalSearchParams<{ id: string }>();
  const myId = useSession((s) => s.user?.id ?? null);
  const detail = useChatDetail(chatId);
  const messages = useMessages(chatId);
  const sendMessage = useSendMessage(chatId);
  const markRead = useMarkRead(chatId);
  const typingMap = useRealtime((s) => s.typing[chatId]);
  const [input, setInput] = useState("");
  const [replyTo, setReplyTo] = useState<Message | null>(null);
  const [pending, setPending] = useState<PendingAttachment[]>([]);
  const [viewerUri, setViewerUri] = useState<string | null>(null);
  const [viewerList, setViewerList] = useState<string[]>([]);
  const [menuFor, setMenuFor] = useState<Message | null>(null);
  const [forwardFor, setForwardFor] = useState<Message | null>(null);
  const [editing, setEditing] = useState<Message | null>(null);
  const lastTypingSent = useRef(0);
  const markReadRef = useRef(false);

  // открытый чат глушит/смывает свои push-уведомления (§3.5)
  useEffect(() => {
    setActiveChatId(chatId);
    return () => setActiveChatId(null);
  }, [chatId]);

  const title = useMemo(() => {
    if (detail.data?.type === "group") return detail.data.title ?? t("chats.title");
    const peer = detail.data?.members.find((m) => m.user_id !== myId)?.user;
    return peer?.display_name ?? "…";
  }, [detail.data, myId]);

  const senderNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of detail.data?.members ?? []) map.set(m.user_id, m.user.display_name);
    return map;
  }, [detail.data]);

  // инвертированная лента: страницы разворачиваются (новые — снизу у inverted)
  const feedData = useMemo(() => {
    const all: (Message | { id: string; __local: true })[] = [];
    for (const page of messages.data?.pages ?? []) all.push(...page.messages);
    return [...all].reverse();
  }, [messages.data]);

  // markRead: при открытии — последнее видимое сообщение (§6, MAX-курсор)
  const lastMessage = feedData[0] as Message | undefined;
  useEffect(() => {
    if (!lastMessage || markReadRef.current) return;
    markReadRef.current = true;
    markRead.mutateAsync(lastMessage.id).catch(() => {});
  }, [lastMessage?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const typingUsers = Object.keys(typingMap ?? {}).filter((uid) => uid !== myId);
  const typingLabel =
    typingUsers.length === 0
      ? null
      : typingUsers.length === 1
        ? `${senderNames.get(typingUsers[0]) ?? "?"} ${t("chat.typing")}`
        : t("chat.typingMany");

  const onInputChange = (text: string) => {
    setInput(text);
    // typing — не чаще раза в 2 c (§16)
    const now = Date.now();
    if (now - lastTypingSent.current > 2000) {
      lastTypingSent.current = now;
      wsClient.sendTyping(chatId);
    }
  };

  const onSend = async () => {
    const text = input.trim();
    // режим редактирования: PATCH вместо отправки нового (edit_bar как в вебе, §6)
    if (editing) {
      if (!text) return;
      const target = editing;
      setEditing(null);
      setInput("");
      await messagesApi.edit(target.id, text).catch(() => {});
      return;
    }
    if (!text && pending.length === 0) return;
    // ждём ready-вложения (уже загруженные в Silo)
    const notReady = pending.find((p) => !p.ready && !p.error);
    if (notReady) return; // UI показывает прогресс
    const attachments = pending
      .filter((p) => p.ready)
      .map((p) => ({
        file_id: p.ready!.file_id,
        kind: p.kind,
        file_name: p.fileName,
      }));
    setInput("");
    setPending([]);
    const replyToId = replyTo?.id;
    setReplyTo(null);
    await sendMessage
      .mutateAsync({ text: text || undefined, attachments, replyToId, idempotencyKey: randomUUID() })
      .catch(() => {
        // ошибка уже отрисована статусом error на сообщении (§3.10)
      });
  };

  const pickImage = async () => {
    // Photo Picker (Android 13+) — permissions не требуются (§3.4)
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 0.9,
    });
    if (res.canceled || res.assets.length === 0) return;
    const asset = res.assets[0];
    attachFile(asset.uri, asset.fileName ?? "photo.jpg", asset.mimeType ?? "image/jpeg", asset.fileSize ?? 0, "image");
  };

  const pickAnyFile = () => {
    // MVP этапа 5: файлы — через ImagePicker (фото/видео); DocumentPicker —
    // этап 6+ (решение в Docs). Кнопка «Файл» открывает тот же Picker.
    void pickImage();
  };

  const attachFile = (
    uri: string,
    fileName: string,
    mimeType: string,
    size: number,
    kind: "image" | "video" | "file",
  ) => {
    const entry: PendingAttachment = {
      fileName,
      localUri: uri,
      kind,
      progress: 0,
      handle: null,
      ready: null,
      error: null,
    };
    setPending((prev) => [...prev, entry]);
    const handle = uploadFile(
      { uri, size, fileName, mimeType },
      (percent) =>
        setPending((prev) =>
          prev.map((p) => (p.localUri === uri ? { ...p, progress: percent } : p)),
        ),
    );
    setPending((prev) => prev.map((p) => (p.localUri === uri ? { ...p, handle } : p)));
    handle.promise
      .then((result) =>
        setPending((prev) =>
          prev.map((p) =>
            p.localUri === uri
              ? { ...p, ready: { file_id: result.fileId, kind }, progress: 100 }
              : p,
          ),
        ),
      )
      .catch((err: Error) => {
        const isTooLarge = err instanceof FileTooLargeError;
        if (isTooLarge) {
          // лимит отклонён ДО PUT (DoD этапа 5)
          setPending((prev) => prev.filter((p) => p.localUri !== uri));
          Alert.alert(t("common.unknownError"), err.message);
          return;
        }
        setPending((prev) =>
          prev.map((p) => (p.localUri === uri ? { ...p, error: err.message } : p)),
        );
      });
  };

  const toggleReaction = async (message: Message, emoji: string) => {
    setMenuFor(null);
    await messagesApi.setReaction(message.id, emoji).catch(() => {});
  };

  const onDelete = async (message: Message) => {
    setMenuFor(null);
    await messagesApi.delete(message.id).catch(() => {});
  };

  const renderItem = useCallback(
    ({ item }: { item: unknown }) => {
      const m = item as Message;
      return (
        <MessageBubble
          message={m}
          isMine={m.sender_id === myId || (m as { status?: string }).status !== undefined}
          senderName={m.sender_id ? senderNames.get(m.sender_id) : undefined}
          onPressAttachment={(att: Attachment) => {
            // картинка → лайтбокс со всеми фото чата (как web Lightbox, §3.10)
            const images = feedData
              .flatMap((m) => ((m as Message).attachments ?? []))
              .filter((a) => a.kind === "image")
              .map((a) => a.url);
            setViewerList(images);
            setViewerUri(att.url);
          }}
          onLongPress={() => setMenuFor(m)}
        />
      );
    },
    [myId, senderNames, feedData],
  );

  return (
    <SafeAreaView style={styles.container} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.back}>
          <Text style={styles.backText}>‹</Text>
        </Pressable>
        <Pressable style={styles.headerCenter} onPress={() => router.push(`/chats/${chatId}/info`)}>
          <Text style={styles.title} numberOfLines={1}>
            {title}
          </Text>
          {typingLabel ? <Text style={styles.typing}>{typingLabel}</Text> : null}
        </Pressable>
      </View>

      <FlatList
        inverted
        data={feedData}
        keyExtractor={(m) => (m as Message).id}
        renderItem={renderItem}
        onEndReachedThreshold={0.4}
        onEndReached={() => {
          // догрузка истории «вверх» (в inverted — визуально вниз списка данных)
          if (messages.hasNextPage && !messages.isFetchingNextPage) void messages.fetchNextPage();
        }}
        ListFooterComponent={
          messages.isFetchingNextPage ? <Text style={styles.historyLoading}>{t("chat.historyLoading")}</Text> : null
        }
        style={styles.feed}
      />

      {replyTo ? (
        <View style={styles.replyBar}>
          <Text style={styles.replyText} numberOfLines={1}>
            {t("chat.replyingTo", { text: replyTo.text ?? "…" })}
          </Text>
          <Pressable onPress={() => setReplyTo(null)}>
            <Text style={styles.replyCancel}>✕</Text>
          </Pressable>
        </View>
      ) : null}

      {editing ? (
        <View style={styles.editBar}>
          <Text style={styles.replyText} numberOfLines={1}>
            {t("edit.title")}
          </Text>
          <Pressable
            onPress={() => {
              setEditing(null);
              setInput("");
            }}
          >
            <Text style={styles.replyCancel}>✕</Text>
          </Pressable>
        </View>
      ) : null}

      {pending.map((p) => (
        <View key={p.localUri} style={styles.pendingRow}>
          <Text style={styles.pendingName} numberOfLines={1}>
            {p.fileName}
          </Text>
          {p.error ? (
            <Text style={styles.pendingError}>{p.error}</Text>
          ) : p.ready ? (
            <Text style={styles.pendingDone}>✓</Text>
          ) : (
            <>
              <Text style={styles.pendingProgress}>{t("chat.attachProgress", { percent: p.progress })}</Text>
              <Pressable
                onPress={() => {
                  p.handle?.abort();
                  setPending((prev) => prev.filter((x) => x.localUri !== p.localUri));
                }}
              >
                <Text style={styles.pendingCancel}>{t("common.cancel")}</Text>
              </Pressable>
            </>
          )}
        </View>
      ))}

      <View style={styles.composer}>
        <Pressable style={styles.attachButton} onPress={pickImage}>
          <Text style={styles.attachIcon}>＋</Text>
        </Pressable>
        <Pressable style={styles.attachButton} onPress={pickAnyFile}>
          <Text style={styles.attachIcon}>📎</Text>
        </Pressable>
        <TextInput
          style={styles.input}
          value={input}
          onChangeText={onInputChange}
          onSubmitEditing={() => void onSend()}
          returnKeyType="send"
          placeholder={t("chat.inputPlaceholder")}
          placeholderTextColor={theme.colors.textSecondary}
        />
        <Pressable style={styles.sendButton} onPress={() => void onSend()}>
          <Text style={styles.sendIcon}>➤</Text>
        </Pressable>
      </View>

      <ImageViewer uri={viewerUri} images={viewerList} onClose={() => setViewerUri(null)} />

      {/* контекстное меню (long-tap): компактный попап — reactbar + действия, как hover-панель веба */}
      <Modal visible={menuFor !== null} transparent animationType="fade" onRequestClose={() => setMenuFor(null)}>
        <Pressable style={styles.menuBackdrop} onPress={() => setMenuFor(null)}>
          <View style={styles.menu}>
            <View style={styles.menuReactions}>
              {/* API принимает имена эмодзи (§6), не символы — как веб (ChatPage EMOJI_SET) */}
              {[
                ["thumbs_up", "👍"],
                ["heart", "❤️"],
                ["laugh", "😄"],
                ["fire", "🔥"],
                ["check", "✅"],
              ].map(([name, char]) => (
                <Pressable
                  key={name}
                  style={styles.menuReactionBtn}
                  onPress={() => menuFor && void toggleReaction(menuFor, name)}
                >
                  <Text style={styles.menuReaction}>{char}</Text>
                </Pressable>
              ))}
            </View>
            <View style={styles.menuActions}>
              {menuFor && menuFor.type === "text" && !menuFor.deleted_at ? (
                <Pressable
                  style={styles.menuActionBtn}
                  onPress={() => {
                    setReplyTo(menuFor);
                    setMenuFor(null);
                  }}
                >
                  <Text style={styles.menuActionIcon}>↩</Text>
                  <Text style={styles.menuActionText}>{t("common.reply")}</Text>
                </Pressable>
              ) : null}
              {menuFor && menuFor.type === "text" && !menuFor.deleted_at ? (
                <Pressable
                  style={styles.menuActionBtn}
                  onPress={() => {
                    setForwardFor(menuFor);
                    setMenuFor(null);
                  }}
                >
                  <Text style={styles.menuActionIcon}>➦</Text>
                  <Text style={styles.menuActionText}>{t("common.forward")}</Text>
                </Pressable>
              ) : null}
              {menuFor && menuFor.sender_id === myId && menuFor.type === "text" && !menuFor.deleted_at ? (
                <Pressable
                  style={styles.menuActionBtn}
                  onPress={() => {
                    setEditing(menuFor);
                    setInput(menuFor.text ?? "");
                    setReplyTo(null);
                    setMenuFor(null);
                  }}
                >
                  <Text style={styles.menuActionIcon}>✎</Text>
                  <Text style={styles.menuActionText}>{t("common.edit")}</Text>
                </Pressable>
              ) : null}
              {menuFor && menuFor.sender_id === myId && menuFor.type === "text" && !menuFor.deleted_at ? (
                <Pressable style={styles.menuActionBtn} onPress={() => menuFor && void onDelete(menuFor)}>
                  <Text style={[styles.menuActionIcon, { color: theme.colors.danger }]}>✕</Text>
                  <Text style={[styles.menuActionText, { color: theme.colors.danger }]}>{t("common.delete")}</Text>
                </Pressable>
              ) : null}
            </View>
          </View>
        </Pressable>
      </Modal>

      {forwardFor ? <ForwardDialog message={forwardFor} onClose={() => setForwardFor(null)} /> : null}
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
  headerCenter: { flex: 1 },
  title: { fontSize: theme.font.lg, fontWeight: "600", color: theme.colors.text },
  typing: { fontSize: theme.font.sm, color: theme.colors.textSecondary },
  feed: { flex: 1 },
  historyLoading: {
    textAlign: "center",
    color: theme.colors.textSecondary,
    paddingVertical: theme.spacing.sm,
    fontSize: theme.font.sm,
  },
  replyBar: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: theme.colors.surface,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.xs,
    borderLeftWidth: 3,
    borderLeftColor: theme.colors.primary,
  },
  replyText: { flex: 1, color: theme.colors.textSecondary, fontSize: theme.font.sm },
  replyCancel: { color: theme.colors.textSecondary, paddingHorizontal: theme.spacing.sm },
  editBar: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: theme.colors.surface,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: theme.spacing.xs,
    borderLeftWidth: 3,
    borderLeftColor: theme.colors.accentGreen,
  },
  pendingRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: theme.spacing.md,
    paddingVertical: 2,
  },
  pendingName: { flex: 1, fontSize: theme.font.sm, color: theme.colors.text },
  pendingProgress: { fontSize: theme.font.sm, color: theme.colors.textSecondary },
  pendingCancel: { fontSize: theme.font.sm, color: theme.colors.danger, marginLeft: 8 },
  pendingError: { fontSize: theme.font.sm, color: theme.colors.danger },
  pendingDone: { fontSize: theme.font.sm, color: theme.colors.accentGreen },
  composer: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: theme.spacing.xs,
    borderTopWidth: 1,
    borderTopColor: theme.colors.border,
  },
  attachButton: { paddingHorizontal: 8, paddingVertical: 8 },
  attachIcon: { fontSize: 20, color: theme.colors.primary },
  input: {
    flex: 1,
    fontSize: theme.font.md,
    color: theme.colors.text,
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.lg,
    paddingHorizontal: theme.spacing.md,
    paddingVertical: 10,
  },
  sendButton: { paddingHorizontal: 10, paddingVertical: 8 },
  sendIcon: { fontSize: 20, color: theme.colors.primary },
  menuBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "center" },
  menu: {
    alignSelf: "center",
    backgroundColor: theme.colors.background,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: theme.spacing.sm,
    borderWidth: 1,
    borderColor: theme.colors.border,
  },
  menuReactions: { flexDirection: "row", justifyContent: "space-between", marginBottom: 4 },
  menuReactionBtn: { padding: 4 },
  menuReaction: { fontSize: 20 },
  menuActions: { flexDirection: "row", alignItems: "center", gap: 2 },
  menuActionBtn: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: theme.radius.sm,
  },
  menuActionIcon: { fontSize: 14, marginRight: 4, color: theme.colors.text },
  menuActionText: { fontSize: theme.font.sm, color: theme.colors.text },
});
