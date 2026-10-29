import { useEffect, useMemo, useRef, useState } from "react";
import type { Attachment, Chat, Message } from "../../api/types";
import { Button } from "../../components/ui";
import { sendMessageWithOutbox } from "./outbox";
import { useMe } from "../auth/queries";
import { useChatMembers, flattenMembers } from "../chats/queries";
import { validateFile, uploadFile, toAttachmentMeta } from "../media/upload";
import { toastError, useToastStore } from "../../stores/ui";
import { ws } from "../../realtime/ws";
import { formatBytes } from "../../lib/format";
import { ApiError } from "../../api/client";

const MAX_LENGTH = 4096;
const ALL_MENTION_THRESHOLD = 100;
const TYPING_INTERVAL_MS = 3000;

interface UploadChip {
  key: string;
  name: string;
  percent: number;
  done: Attachment | null;
  error: string | null;
}

interface MentionCandidate {
  id: string;
  username: string;
  full_name: string;
}

export function Composer({
  chat,
  replyTo,
  onClearReply,
}: {
  chat: Chat | undefined;
  replyTo: Message | null;
  onClearReply: () => void;
}) {
  const me = useMe();
  const [text, setText] = useState("");
  const [chips, setChips] = useState<UploadChip[]>([]);
  const [blockedUntil, setBlockedUntil] = useState(0);
  const [, setTick] = useState(0);
  const [mention, setMention] = useState<{ query: string; start: number } | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const typingSentAt = useRef(0);
  const typingStopTimer = useRef<number | null>(null);

  const members = useChatMembers(chat?.id);
  const memberUsers = useMemo(
    () => flattenMembers(members.data).map((entry) => entry.user),
    [members.data],
  );

  const now = Date.now();
  const blocked = blockedUntil > now;
  const overLimit = text.length > MAX_LENGTH;
  const busyUploading = chips.some((chip) => !chip.done && !chip.error);
  const canSend =
    !!chat && !overLimit && !busyUploading && (text.trim().length > 0 || chips.some((chip) => chip.done));
  const blockedSeconds = Math.max(0, Math.ceil((blockedUntil - now) / 1000));

  useEffect(() => {
    if (!blocked) return;
    const timer = window.setInterval(() => {
      setTick((value) => value + 1);
      setBlockedUntil((value) => (value > Date.now() ? value : 0));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [blocked]);

  useEffect(() => {
    if (replyTo) textareaRef.current?.focus();
  }, [replyTo]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [text]);

  const mentionCandidates = useMemo((): MentionCandidate[] => {
    if (!mention) return [];
    const q = mention.query.toLowerCase();
    const result: MentionCandidate[] = memberUsers
      .filter(
        (user) => user.username.toLowerCase().includes(q) || user.full_name.toLowerCase().includes(q),
      )
      .slice(0, 8)
      .map((user) => ({ id: user.id, username: user.username, full_name: user.full_name }));
    const allowAll = !!chat && (chat.my_role !== "member" || chat.members_count <= ALL_MENTION_THRESHOLD);
    if (allowAll && "all".includes(q)) {
      result.push({ id: "__all", username: "all", full_name: "Все участники" });
    }
    return result;
  }, [mention, memberUsers, chat]);

  const sendTyping = (start: boolean) => {
    if (!chat) return;
    ws.sendTyping(chat.id, start);
  };

  const onTextChange = (value: string) => {
    setText(value);
    const el = textareaRef.current;
    if (el) {
      const caret = el.selectionStart ?? value.length;
      const before = value.slice(0, caret);
      const match = /(^|\s)@([a-zA-Z0-9_.-]*)$/.exec(before);
      if (match) {
        setMention({ query: match[2], start: caret - match[2].length - 1 });
        setMentionIndex(0);
      } else {
        setMention(null);
      }
    }
    const nowTs = Date.now();
    if (nowTs - typingSentAt.current > TYPING_INTERVAL_MS) {
      typingSentAt.current = nowTs;
      sendTyping(true);
    }
    if (typingStopTimer.current) window.clearTimeout(typingStopTimer.current);
    typingStopTimer.current = window.setTimeout(() => sendTyping(false), 3500);
  };

  const insertMention = (username: string) => {
    if (!mention) return;
    setText(
      (prev) =>
        prev.slice(0, mention.start) +
        "@" +
        username +
        " " +
        prev.slice(mention.start + 1 + mention.query.length),
    );
    setMention(null);
    textareaRef.current?.focus();
  };

  const send = () => {
    if (!chat || !canSend || !me.data) return;
    const attachments = chips.filter((chip) => chip.done).map((chip) => chip.done as Attachment);
    sendMessageWithOutbox(
      chat.id,
      me.data.id,
      {
        body: text.trim(),
        attachments: attachments.map((attachment) => attachment.file_id),
        reply_to_seq: replyTo ? replyTo.seq : null,
      },
      attachments,
    );
    setText("");
    setChips([]);
    onClearReply();
    setMention(null);
    sendTyping(false);
    if (typingStopTimer.current) window.clearTimeout(typingStopTimer.current);
    textareaRef.current?.focus();
  };

  const pickFiles = (files: FileList | null) => {
    if (!files || !files.length) return;
    for (const file of Array.from(files)) {
      const error = validateFile(file, chips.filter((chip) => !chip.error).length);
      if (error) {
        useToastStore.getState().push({ kind: "error", title: "Файл не принят", body: error });
        continue;
      }
      const key = `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      setChips((prev) => [...prev, { key, name: file.name, percent: 0, done: null, error: null }]);
      uploadFile(file, (percent) => {
        setChips((prev) => prev.map((chip) => (chip.key === key ? { ...chip, percent } : chip)));
      })
        .then((result) => {
          setChips((prev) =>
            prev.map((chip) =>
              chip.key === key ? { ...chip, percent: 100, done: toAttachmentMeta(result) } : chip,
            ),
          );
        })
        .catch((uploadError: unknown) => {
          if (uploadError instanceof ApiError && uploadError.status === 429) {
            setBlockedUntil(Date.now() + 30000);
          }
          const message = uploadError instanceof Error ? uploadError.message : "Ошибка загрузки";
          setChips((prev) => prev.map((chip) => (chip.key === key ? { ...chip, error: message } : chip)));
        });
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  if (!chat) {
    return (
      <div className="composer">
        <div className="center-note" style={{ padding: 8 }}>
          Загрузка чата…
        </div>
      </div>
    );
  }

  return (
    <div className="composer">
      {mention && mentionCandidates.length ? (
        <div className="mention-pop">
          {mentionCandidates.map((user, index) => (
            <button
              key={user.id}
              className={`mention-item${index === mentionIndex ? " hl" : ""}`}
              onMouseDown={(event) => {
                event.preventDefault();
                insertMention(user.username);
              }}
            >
              <strong>@{user.username}</strong>
              <span className="m-username">{user.full_name}</span>
            </button>
          ))}
        </div>
      ) : null}

      {replyTo ? (
        <div className="composer-reply">
          <strong style={{ color: "var(--accent)" }}>Ответ:</strong>
          <span className="r-body">
            {replyTo.body.slice(0, 100) || `вложение (${replyTo.attachments.length})`}
          </span>
          <Button variant="ghost" className="sm" onClick={onClearReply}>
            ✕
          </Button>
        </div>
      ) : null}

      {chips.length ? (
        <div className="composer-uploads">
          {chips.map((chip) => (
            <div key={chip.key} className="upload-chip">
              <span className="u-name">{chip.name}</span>
              {chip.error ? (
                <>
                  <span style={{ color: "var(--danger)" }}>ошибка</span>
                  <Button
                    variant="ghost"
                    className="sm"
                    onClick={() => setChips((prev) => prev.filter((c) => c.key !== chip.key))}
                  >
                    ✕
                  </Button>
                </>
              ) : chip.done ? (
                <span style={{ color: "var(--success)" }}>✓ {formatBytes(chip.done.size_bytes)}</span>
              ) : (
                <span style={{ color: "var(--text-3)" }}>{chip.percent}%</span>
              )}
            </div>
          ))}
        </div>
      ) : null}

      <div className="composer-input-row">
        <Button variant="ghost" className="icon" onClick={() => fileRef.current?.click()} title="Прикрепить файл">
          📎
        </Button>
        <input ref={fileRef} type="file" multiple hidden onChange={(event) => pickFiles(event.target.files)} />
        <textarea
          ref={textareaRef}
          value={text}
          placeholder={
            blocked
              ? `Лимит отправки — подождите ${blockedSeconds} с`
              : "Сообщение…  Enter — отправить, Shift+Enter — перенос"
          }
          disabled={blocked}
          onChange={(event) => onTextChange(event.target.value)}
          onKeyDown={(event) => {
            if (mention && mentionCandidates.length) {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setMentionIndex((index) => Math.min(index + 1, mentionCandidates.length - 1));
                return;
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                setMentionIndex((index) => Math.max(index - 1, 0));
                return;
              }
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                const candidate = mentionCandidates[mentionIndex];
                if (candidate) insertMention(candidate.username);
                return;
              }
              if (event.key === "Escape") {
                setMention(null);
                return;
              }
            }
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
          onPaste={(event) => {
            const files = event.clipboardData?.files;
            if (files && files.length) {
              event.preventDefault();
              pickFiles(files);
            }
          }}
        />
        <Button variant="primary" className="icon" disabled={!canSend || blocked} onClick={send} title="Отправить">
          ➤
        </Button>
      </div>

      <div className="composer-meta">
        {blocked ? <span className="rate">Лимит отправки, подождите…</span> : null}
        {overLimit ? (
          <span className="over">
            {text.length}/{MAX_LENGTH}
          </span>
        ) : text.length > MAX_LENGTH * 0.8 ? (
          <span>
            {text.length}/{MAX_LENGTH}
          </span>
        ) : null}
      </div>
    </div>
  );
}
