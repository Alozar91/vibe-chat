import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { InfiniteData } from "@tanstack/react-query";
import type { Chat, Message, MessagesPage } from "../../api/types";
import { formatTime } from "../../lib/time";
import { renderMessageHtml } from "../../lib/markdown";
import { Avatar } from "../../components/ui";
import { useMe, useUser } from "../auth/queries";
import { AttachmentGrid } from "../media/AttachmentView";
import { useEditMessage, useDeleteMessage, messagesKey } from "./queries";
import { outbox } from "./outbox";
import { toastError, useUiStore } from "../../stores/ui";

export function MessageBubble({
  message,
  out,
  grouped,
  chat,
  readByOthers,
  onReply,
  onForward,
}: {
  message: Message;
  out: boolean;
  grouped: boolean;
  chat: Chat | undefined;
  readByOthers: boolean;
  onReply: () => void;
  onForward: () => void;
}) {
  const me = useMe();
  const sender = useUser(out ? null : message.sender_id);
  const [editing, setEditing] = useState(false);
  const [editBody, setEditBody] = useState(message.body);
  const edit = useEditMessage(message.chat_id);
  const remove = useDeleteMessage(message.chat_id);

  const isDeleted = !!message.deleted_at;
  const isTemp = message.seq < 0;
  const myRole = chat?.my_role || "member";
  const canEdit = out && !isDeleted && !isTemp;
  const canDelete = (out || myRole === "owner" || myRole === "admin") && !isDeleted && !isTemp;
  const senderName = out ? "Вы" : sender.data?.full_name || "…";

  if (isDeleted) {
    return (
      <div className={`msg-row${out ? " out" : ""}`} data-seq={message.seq}>
        <span className="msg-avatar-slot" />
        <div className="msg-bubble" style={{ opacity: 0.55, fontStyle: "italic" }}>
          Сообщение удалено
          <span className="msg-meta">{formatTime(message.created_at)}</span>
        </div>
      </div>
    );
  }

  const submitEdit = async () => {
    const body = editBody.trim();
    if (!body) return;
    try {
      await edit.mutateAsync({ seq: message.seq, body });
      setEditing(false);
    } catch (error) {
      toastError(error, "Не удалось сохранить правку");
    }
  };

  const confirmDelete = async () => {
    if (!window.confirm("Удалить сообщение?")) return;
    try {
      await remove.mutateAsync(message.seq);
    } catch (error) {
      toastError(error, "Не удалось удалить сообщение");
    }
  };

  const retryFailed = () => {
    const client = message._client;
    if (!client) return;
    outbox.retry(message.chat_id, client.key);
  };

  return (
    <div className={`msg-row${out ? " out" : ""}${grouped ? " cont" : ""}`} data-seq={message.seq}>
      <span className="msg-avatar-slot">
        {grouped ? null : <Avatar name={senderName} url={sender.data?.avatar_url} seed={message.sender_id} size={34} />}
      </span>
      <div className="msg-bubble">
        <div className="msg-actions">
          <button className="msg-action-btn" title="Ответить" onClick={onReply}>
            ↩
          </button>
          <button className="msg-action-btn" title="Переслать" onClick={onForward}>
            ➦
          </button>
          {canEdit ? (
            <button
              className="msg-action-btn"
              title="Редактировать"
              onClick={() => {
                setEditBody(message.body);
                setEditing(true);
              }}
            >
              ✎
            </button>
          ) : null}
          {canDelete ? (
            <button className="msg-action-btn danger" title="Удалить" onClick={() => void confirmDelete()}>
              ✕
            </button>
          ) : null}
        </div>

        {!grouped && !out ? <div className="msg-sender">{senderName}</div> : null}

        {message.reply_to_seq ? <ReplyPreview chatId={message.chat_id} replyToSeq={message.reply_to_seq} /> : null}

        {message.data?.forwarded_from && (message.data.forwarded_from as unknown[]).length ? (
          <div className="msg-forwarded">Переслано ({(message.data.forwarded_from as unknown[]).length})</div>
        ) : null}

        {editing ? (
          <div>
            <textarea
              className="textarea"
              value={editBody}
              rows={3}
              autoFocus
              onChange={(event) => setEditBody(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void submitEdit();
                }
                if (event.key === "Escape") setEditing(false);
              }}
            />
            <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", marginTop: 6 }}>
              <button className="btn sm" onClick={() => setEditing(false)}>
                Отмена
              </button>
              <button className="btn sm primary" disabled={edit.isPending} onClick={() => void submitEdit()}>
                Сохранить
              </button>
            </div>
          </div>
        ) : (
          <>
            {message.body ? (
              <div
                className="msg-text"
                dangerouslySetInnerHTML={{
                  __html: renderMessageHtml(message.body, {
                    myUsername: me.data?.username,
                    highlightMentions: true,
                  }),
                }}
              />
            ) : null}
            {message.attachments.length ? <AttachmentGrid attachments={message.attachments} /> : null}
          </>
        )}

        <span className="msg-meta">
          {formatTime(message.created_at)}
          {message.edited_at ? " · изм." : null}
          {message._client ? (
            message._client.status === "sending" ? (
              <span className="msg-status" title="Отправка…">
                ⏳
              </span>
            ) : message._client.status === "failed" ? (
              <span
                className="msg-status failed"
                title={message._client.error || "Ошибка отправки — нажмите, чтобы повторить"}
                onClick={retryFailed}
              >
                !
              </span>
            ) : null
          ) : out ? (
            readByOthers ? (
              <span title="Прочитано">✓✓</span>
            ) : (
              <span title="Отправлено">✓</span>
            )
          ) : null}
        </span>
      </div>
    </div>
  );
}

function ReplyPreview({ chatId, replyToSeq }: { chatId: string; replyToSeq: number }) {
  const qc = useQueryClient();
  const found = useMemo(() => {
    const data = qc.getQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId));
    if (!data) return null;
    for (const page of data.pages) {
      const hit = page.items.find((item) => item.seq === replyToSeq);
      if (hit) return hit;
    }
    return null;
  }, [qc, chatId, replyToSeq]);
  const author = useUser(found?.sender_id ?? null);

  return (
    <div
      className="msg-reply"
      onClick={() => document.querySelector(`[data-seq="${replyToSeq}"]`)?.scrollIntoView({ block: "center" })}
    >
      <span className="r-author">{found ? (author.data?.full_name || "…") : `#${replyToSeq}`}</span>
      <div className="r-body">
        {found
          ? found.attachments.length && !found.body
            ? `📎 ${found.attachments[0].name}`
            : found.body.slice(0, 120)
          : "Сообщение вне загруженной истории"}
      </div>
    </div>
  );
}
