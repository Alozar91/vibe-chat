/**
 * Компоненты ленты (§3.10): пузырь сообщения (вход/выход), статусы отправки
 * sending/sent/error+retry, вложения (сетка картинок + список файлов),
 * удалённые — плашка, реакции.
 */

import { Alert, Image, Pressable, StyleSheet, Text, View } from "react-native";
import { useState } from "react";
import type { Attachment, LocalMessage, Message } from "../api/types";
import { useCachedMedia } from "../hooks/use-cached-media";
import { useRetryMessage } from "../hooks/use-send-message";
import { t } from "../i18n/ru";
import { theme } from "../theme";

export const REACTIONS = ["👍", "❤️", "😄", "🔥", "✅"] as const;

function AttachmentImage({ att }: { att: Attachment }) {
  // thumb (§8) — всегда для image; blurhash-рендер отложен (нужна нативная
  // библиотека), плейсхолдер — surface (решение зафиксировано в Docs)
  const uri = useCachedMedia(att.file_id, att.thumb_url ?? att.url);
  return (
    <Image
      source={uri ? { uri } : undefined}
      style={[styles.attImage, !uri && { backgroundColor: theme.colors.surface }]}
    />
  );
}

function AttachmentFileRow({ att }: { att: Attachment }) {
  return (
    <View style={styles.attFileRow}>
      <Text style={styles.attFileIcon}>📎</Text>
      <Text style={styles.attFileName} numberOfLines={1}>
        {att.file_name}
      </Text>
    </View>
  );
}

export function MessageBubble({
  message,
  isMine,
  senderName,
  onPressAttachment,
  onLongPress,
}: {
  message: Message | LocalMessage;
  isMine: boolean;
  senderName?: string;
  onPressAttachment?: (att: Attachment) => void;
  onLongPress?: () => void;
}) {
  const retry = useRetryMessage(message.chat_id);
  const local = message as LocalMessage;

  if (message.deleted_at) {
    return (
      <View style={[styles.deletedPlate, isMine ? styles.alignEnd : null]}>
        <Text style={styles.deletedText}>{t("chat.deletedMessage")}</Text>
      </View>
    );
  }

  const images = message.attachments.filter((a) => a.kind === "image");
  const others = message.attachments.filter((a) => a.kind !== "image");
  const hasContent = Boolean(message.text) || message.attachments.length > 0;

  return (
    <View style={[styles.bubbleRow, isMine ? styles.alignEnd : null]}>
      <Pressable
        onLongPress={onLongPress}
        style={[
          styles.bubble,
          isMine ? styles.bubbleOut : styles.bubbleIn,
          message.type === "system" && styles.bubbleSystem,
        ]}
      >
        {!isMine && message.type !== "system" && senderName ? (
          <Text style={styles.senderName}>{senderName}</Text>
        ) : null}
        {message.forward_from_message_id ? (
          <Text style={styles.forwardMark}>пересланное</Text>
        ) : null}
        <View style={styles.imageGrid}>
          {images.map((att) => (
            <Pressable key={att.id} onPress={() => onPressAttachment?.(att)}>
              <AttachmentImage att={att} />
            </Pressable>
          ))}
        </View>
        {others.map((att) => (
          <AttachmentFileRow key={att.id} att={att} />
        ))}
        {message.text ? (
          <Text style={[styles.bubbleText, isMine && styles.bubbleTextOut]}>{message.text}</Text>
        ) : null}
        <View style={styles.metaRow}>
          {message.edited_at ? <Text style={styles.meta}>{t("chat.editedMark")}</Text> : null}
          {message.type === "system" ? null : <MetaStatus message={message} />}
        </View>
        {message.reactions.length > 0 ? (
          <View style={styles.reactionsRow}>
            {message.reactions.map((r) => (
              <Text key={r.emoji} style={styles.reactionChip}>
                {r.emoji} {r.user_ids.length}
              </Text>
            ))}
          </View>
        ) : null}
      </Pressable>
      {/* кнопка «повторить» — только мои error-сообщения (§3.10) */}
      {isMine && local.status === "error" ? (
        <Pressable
          style={styles.retryButton}
          onPress={() => retry.mutateAsync(local).catch(() => {})}
        >
          <Text style={styles.retryText}>{t("common.retry")}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function MetaStatus({ message }: { message: Message | LocalMessage }) {
  const status = (message as LocalMessage).status;
  if (status === "sending") {
    return <Text style={styles.meta}>{t("chat.statusSending")}</Text>;
  }
  if (status === "error") {
    return <Text style={[styles.meta, { color: theme.colors.danger }]}>{t("chat.statusError")}</Text>;
  }
  if (status === "sent") return null; // серверные сообщения без статуса — тоже sent
  return null;
}

/** Просмотрщик картинок — fullscreen-модал (тап по превью). */
export function ImageViewer({ uri, onClose }: { uri: string | null; onClose: () => void }) {
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  if (!uri) return null;
  return (
    <View style={styles.viewerBackdrop}>
      <Pressable style={styles.viewerCloseArea} onPress={onClose} />
      <Image
        source={{ uri }}
        style={styles.viewerImage}
        resizeMode="contain"
        onError={() => Alert.alert(t("common.unknownError"))}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  bubbleRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    paddingHorizontal: theme.spacing.md,
    marginVertical: 2,
  },
  alignEnd: { alignSelf: "flex-end" },
  bubble: {
    maxWidth: "85%",
    borderRadius: theme.radius.lg,
    paddingVertical: theme.spacing.sm,
    paddingHorizontal: theme.spacing.md,
  },
  bubbleOut: { backgroundColor: theme.colors.bubbleOut, borderBottomRightRadius: theme.radius.sm },
  bubbleIn: { backgroundColor: theme.colors.bubbleIn, borderBottomLeftRadius: theme.radius.sm },
  bubbleSystem: {
    backgroundColor: theme.colors.surface,
    alignSelf: "center",
    maxWidth: "95%",
  },
  senderName: {
    fontSize: theme.font.sm,
    fontWeight: "600",
    color: theme.colors.primary,
    marginBottom: 2,
  },
  forwardMark: { fontSize: theme.font.sm, color: theme.colors.textSecondary, marginBottom: 2 },
  bubbleText: { fontSize: theme.font.md, color: theme.colors.text, marginTop: 2 },
  bubbleTextOut: { color: theme.colors.text },
  metaRow: { flexDirection: "row", gap: 6, marginTop: 2 },
  meta: { fontSize: 10, color: theme.colors.textSecondary },
  imageGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 4,
    marginTop: 2,
  },
  attImage: { width: 140, height: 140, borderRadius: theme.radius.md },
  attFileRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: theme.spacing.xs,
    marginTop: 4,
    maxWidth: 240,
  },
  attFileIcon: { marginRight: 6 },
  attFileName: { color: theme.colors.text, fontSize: theme.font.sm, flexShrink: 1 },
  reactionsRow: { flexDirection: "row", gap: 6, marginTop: 4 },
  reactionChip: {
    fontSize: theme.font.sm,
    backgroundColor: theme.colors.background,
    borderRadius: theme.radius.full,
    overflow: "hidden",
    paddingHorizontal: 6,
    paddingVertical: 1,
    color: theme.colors.text,
  },
  deletedPlate: {
    paddingHorizontal: theme.spacing.md,
    marginVertical: 2,
  },
  deletedText: {
    fontSize: theme.font.sm,
    color: theme.colors.textSecondary,
    fontStyle: "italic",
    backgroundColor: theme.colors.surface,
    borderRadius: theme.radius.md,
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: theme.spacing.xs,
    alignSelf: "flex-start",
  },
  retryButton: {
    marginLeft: theme.spacing.sm,
    paddingHorizontal: theme.spacing.sm,
    paddingVertical: 4,
    borderRadius: theme.radius.md,
    backgroundColor: theme.colors.errorBg,
  },
  retryText: { color: theme.colors.danger, fontSize: theme.font.sm },
  viewerBackdrop: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(0,0,0,0.95)",
    alignItems: "center",
    justifyContent: "center",
  },
  viewerCloseArea: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  viewerImage: { width: "100%", height: "80%" },
});
