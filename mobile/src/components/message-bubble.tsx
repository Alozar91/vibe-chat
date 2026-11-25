/**
 * Компоненты ленты (§3.10): пузырь сообщения (вход/выход), статусы отправки
 * sending/sent/error+retry, вложения (сетка картинок + список файлов),
 * удалённые — плашка, реакции.
 */

import { Alert, Image, Modal, PanResponder, Pressable, StyleSheet, Text, View } from "react-native";
import { useEffect, useRef, useState } from "react";
import type { Attachment, LocalMessage, Message } from "../api/types";
import { useCachedMedia } from "../hooks/use-cached-media";
import { useRetryMessage } from "../hooks/use-send-message";
import { t } from "../i18n/ru";
import { theme } from "../theme";

/** Имя эмодзи → символ (API хранит имена, §6; как EMOJI у веба) */
export const EMOJI_CHAR: Record<string, string> = {
  thumbs_up: "👍",
  heart: "❤️",
  laugh: "😄",
  fire: "🔥",
  check: "✅",
};

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
                {EMOJI_CHAR[r.emoji] ?? r.emoji} {r.user_ids.length}
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

/** Просмотрщик картинок — fullscreen-модал (тап по превью). Modal — как меню чата:
 * рисуется над всем экраном и гарантированно ловит тачи (plain absolute View
 * внутри Stack-экрана тап по фону не получал). images — все фото чата:
 * свайп/стрелки листают (как web Lightbox, §3.10). */
export function ImageViewer({
  uri,
  images = [],
  onClose,
}: {
  uri: string | null;
  images?: string[];
  onClose: () => void;
}) {
  // локальный uri поверх пропа: свайп не перезаписывается родителем до onClose
  const [navUri, setNavUri] = useState<string | null>(null);
  const current = navUri ?? uri;
  // индекс и счётчик — по current (иначе counter не двигается при стрелках)
  const index = Math.max(0, images.indexOf(current ?? ""));
  const hasMany = images.length > 1;
  const go = (delta: number) => {
    const next = images[index + delta];
    if (next) setNavUri(next);
  };
  useEffect(() => {
    if (uri === null) setNavUri(null);
  }, [uri]);
  // актуальные данные для PanResponder (useRef создаётся once — замыкание устаревает)
  const stateRef = useRef({ images, index });
  stateRef.current = { images, index };
  const pan = useRef(PanResponder.create({
    onMoveShouldSetPanResponder: (_, g) => Math.abs(g.dx) > 30 && Math.abs(g.dx) > Math.abs(g.dy),
    onPanResponderEnd: (_, g) => {
      const { images: imgs, index: i } = stateRef.current;
      if (g.dx < -40) setNavUri(imgs[i + 1] ?? null);
      else if (g.dx > 40) setNavUri(imgs[i - 1] ?? null);
    },
  })).current;
  return (
    <Modal visible={uri !== null} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.viewerBackdrop} {...(hasMany ? pan.panHandlers : {})}>
        {/* закрытие: Pressable-фоном (как проверено в e2e — тач доходит),
            nav-стрелки/счётчик поверх, pointerEvents только на них */}
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose}>
          <Image
            source={{ uri: current ?? "" }}
            style={styles.viewerImage}
            resizeMode="contain"
            onError={() => Alert.alert(t("common.unknownError"))}
          />
        </Pressable>
        {hasMany ? (
          <View style={styles.viewerNav} pointerEvents="box-none">
            <Pressable style={styles.viewerNavBtn} onPress={() => go(-1)}>
              <Text style={styles.viewerNavText}>‹</Text>
            </Pressable>
            <Text style={styles.viewerCounter}>
              {index + 1} / {images.length}
            </Text>
            <Pressable style={styles.viewerNavBtn} onPress={() => go(1)}>
              <Text style={styles.viewerNavText}>›</Text>
            </Pressable>
          </View>
        ) : null}
      </View>
    </Modal>
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
  viewerImage: { width: "100%", height: "80%" },
  viewerNav: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    alignSelf: "stretch",
    paddingHorizontal: theme.spacing.md,
    // над dev-banner RN и системной пилюлей (в e2e-баннер перекрывал навигацию)
    position: "absolute",
    bottom: theme.spacing.xl,
    left: 0,
    right: 0,
    paddingBottom: 0,
  },
  viewerNavBtn: { padding: theme.spacing.md },
  viewerNavText: { color: "#fff", fontSize: 32, lineHeight: 38 },
  viewerCounter: { color: "#fff", fontSize: theme.font.sm },
});
