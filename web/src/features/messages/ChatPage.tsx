import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import type { InfiniteData } from "@tanstack/react-query";
import type { Chat, Message, MessagesPage } from "../../api/types";
import { formatDay } from "../../lib/time";
import { Avatar, Button, Spinner } from "../../components/ui";
import { useUiStore } from "../../stores/ui";
import { flattenMessages, useMessages, maxSeqOfCache, messagesKey } from "./queries";
import { messagesApi } from "../../api/endpoints";
import { MessageBubble } from "./MessageBubble";
import { Composer } from "./Composer";
import { ForwardDialog } from "./ForwardDialog";
import { ChatInfoPanel } from "../chats/ChatInfoPanel";
import { chatTitle } from "../chats/ChatList";
import { useChat, useChatMembers, flattenMembers, markRead, chatsFromCache } from "../chats/queries";
import { useMe, useUser } from "../auth/queries";
import { setActiveChat } from "../../realtime/active";
import { updateLastChat } from "../../lib/lastChat";
import { appNavigate } from "../../realtime/navigator";

const GROUP_WINDOW_MS = 5 * 60_000;

export function ChatPage({ chatId }: { chatId: string }) {
  const qc = useQueryClient();
  const me = useMe();
  const meId = me.data?.id;
  const [searchParams, setSearchParams] = useSearchParams();
  const [infoOpen, setInfoOpen] = useState(false);
  const [replyTo, setReplyTo] = useState<Message | null>(null);
  const [forwardMessage, setForwardMessage] = useState<Message | null>(null);
  const [newCount, setNewCount] = useState(0);
  const [atBottom, setAtBottom] = useState(true);

  const chatQuery = useChat(chatId);
  const chatFromList = useMemo(
    () => chatsFromCache(qc).find((item) => item.id === chatId),
    [qc, chatId],
  );
  const chat = chatQuery.data || chatFromList;

  const messagesQuery = useMessages(chatId);
  const flat = useMemo(() => flattenMessages(messagesQuery.data), [messagesQuery.data]);

  const members = useChatMembers(chatId);
  const memberEntries = flattenMembers(members.data);
  const maxOtherRead = useMemo(() => {
    let max = 0;
    for (const entry of memberEntries) {
      if (entry.user.id !== meId && entry.last_read_seq > max) max = entry.last_read_seq;
    }
    return max;
  }, [memberEntries, meId]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const firstLoadDone = useRef(false);
  const prevLastSeq = useRef<number | null>(null);
  const unreadBoundary = useRef<number | null>(null);
  if (unreadBoundary.current === null && chat) {
    unreadBoundary.current = Math.max(chat.last_message_seq - chat.unread, 0);
  }

  const wsStatus = useUiStore((state) => state.wsStatus);
  const typingMap = useUiStore((state) => state.typing[chatId]);

  useEffect(() => {
    setActiveChat(chatId);
    updateLastChat(chatId);
    setNewCount(0);
    return () => setActiveChat(null);
  }, [chatId]);

  useEffect(() => {
    if (messagesQuery.isPending || firstLoadDone.current) return;
    firstLoadDone.current = true;
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
  }, [messagesQuery.isPending, chatId]);

  const lastSeq = flat.length ? flat[flat.length - 1].seq : null;

  useEffect(() => {
    if (lastSeq === null) return;
    const prev = prevLastSeq.current;
    prevLastSeq.current = lastSeq;
    if (prev === null || lastSeq <= prev) return;
    const lastMessage = flat[flat.length - 1];
    const isMine = lastMessage?.sender_id === meId;
    if (atBottom || isMine) {
      requestAnimationFrame(() => {
        bottomRef.current?.scrollIntoView({ block: "end" });
      });
      setNewCount(0);
    } else {
      setNewCount((count) => count + 1);
    }
  }, [lastSeq, atBottom, flat, meId]);

  useEffect(() => {
    if (!chat || messagesQuery.isPending) return;
    if (document.visibilityState !== "visible") return;
    const target = Math.max(chat.last_message_seq, maxSeqOfCache(qc, chatId) ?? 0);
    if (target <= 0) return;
    const timer = window.setTimeout(() => {
      void markRead(qc, chatId, target);
    }, 600);
    return () => window.clearTimeout(timer);
  }, [chatId, chat, messagesQuery.isPending, flat.length, qc]);

  const highlightSeq = searchParams.get("m") ? Number(searchParams.get("m")) : null;

  useEffect(() => {
    if (highlightSeq === null || messagesQuery.isPending) return;
    const target = highlightSeq;
    setSearchParams({}, { replace: true });
    requestAnimationFrame(() => {
      const element = document.querySelector(`[data-seq="${target}"]`);
      if (element) {
        element.scrollIntoView({ block: "center" });
        return;
      }
      void jumpToSeq(qc, chatId, target);
    });
  }, [highlightSeq, messagesQuery.isPending, qc, chatId, setSearchParams]);

  const topSentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = topSentinelRef.current;
    if (!element || !messagesQuery.hasNextPage) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries[0].isIntersecting || messagesQuery.isFetchingNextPage) return;
        const heightBefore = scrollRef.current?.scrollHeight ?? 0;
        void messagesQuery.fetchNextPage().then(() => {
          requestAnimationFrame(() => {
            const heightAfter = scrollRef.current?.scrollHeight ?? 0;
            scrollRef.current?.scrollBy({ top: heightAfter - heightBefore });
          });
        });
      },
      { rootMargin: "300px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [messagesQuery.hasNextPage, messagesQuery.isFetchingNextPage, flat.length]);

  const typingUserIds = Object.keys(typingMap || {}).filter((userId) => userId !== meId);
  const chatResolved = chat as Chat | undefined;
  const title = chatResolved ? chatTitle(chatResolved) : "…";

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    setAtBottom(nearBottom);
    if (nearBottom) setNewCount(0);
  };

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ block: "end" });
    setNewCount(0);
  };

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0, position: "relative" }}>
      <div style={{ display: "flex", flexDirection: "column", flex: 1, minWidth: 0 }}>
        <div className="chat-header">
          <Button variant="ghost" className="icon mobile-only" onClick={() => appNavigate("/")} aria-label="Назад">
            ‹
          </Button>
          <Avatar
            name={title}
            url={chatResolved?.type === "direct" ? chatResolved.counterpart?.avatar_url : chatResolved?.avatar_url}
            seed={chatId}
            size={40}
          />
          <div className="chat-header-info">
            <div className="chat-header-title">{title}</div>
            <div className="chat-header-sub">
              {typingUserIds.length ? (
                <TypingNames userIds={typingUserIds} />
              ) : chatResolved?.type === "direct" ? (
                <DirectPresence userId={chatResolved.counterpart?.id || null} />
              ) : (
                `${chatResolved?.members_count ?? "…"} участников`
              )}
            </div>
          </div>
          {wsStatus !== "online" ? <span className="ws-dot offline" title="Нет связи в реальном времени" /> : null}
          <Button variant="ghost" onClick={() => setInfoOpen((open) => !open)} aria-label="Информация о чате">
            ⋯
          </Button>
        </div>

        <div className="messages-wrap">
          <div className="messages-scroll" ref={scrollRef} onScroll={onScroll}>
            <div ref={topSentinelRef} />
            {messagesQuery.isPending ? (
              <div style={{ padding: 30 }}>
                <Spinner />
              </div>
            ) : null}
            {flat.map((message, index) => {
              const prev = flat[index - 1];
              const showDay =
                !prev || formatDay(prev.created_at) !== formatDay(message.created_at);
              const boundary = unreadBoundary.current;
              const showUnreadSep =
                boundary !== null &&
                message.seq > 0 &&
                message.seq > boundary &&
                (!prev || prev.seq <= boundary || prev.seq < 0);
              const isGrouped =
                !showDay &&
                !!prev &&
                prev.seq > 0 &&
                message.seq > 0 &&
                prev.sender_id === message.sender_id &&
                prev.type !== "system" &&
                message.type !== "system" &&
                new Date(message.created_at).getTime() - new Date(prev.created_at).getTime() < GROUP_WINDOW_MS;
              return (
                <div key={message.seq > 0 ? `s${message.seq}` : `t${message._client?.key || message.seq}`}>
                  {showDay ? <div className="day-separator">{formatDay(message.created_at)}</div> : null}
                  {showUnreadSep ? <div className="unread-separator">Непрочитанные</div> : null}
                  {message.type === "system" ? (
                    <div className="msg-system">{message.body}</div>
                  ) : (
                    <MessageBubble
                      message={message}
                      out={message.sender_id === meId}
                      grouped={isGrouped}
                      chat={chatResolved}
                      readByOthers={message.seq > 0 && message.seq <= maxOtherRead}
                      onReply={() => setReplyTo(message)}
                      onForward={() => setForwardMessage(message)}
                    />
                  )}
                </div>
              );
            })}
            <div ref={bottomRef} />
          </div>
          {!atBottom || newCount > 0 ? (
            <Button className="scroll-down-btn" onClick={scrollToBottom}>
              Вниз{newCount > 0 ? ` · ${newCount}` : ""}
            </Button>
          ) : null}
        </div>

        <Composer chat={chatResolved} replyTo={replyTo} onClearReply={() => setReplyTo(null)} />
      </div>

      {infoOpen && chatResolved ? <ChatInfoPanel chat={chatResolved} onClose={() => setInfoOpen(false)} /> : null}
      {forwardMessage && chatResolved ? <ForwardDialog message={forwardMessage} onClose={() => setForwardMessage(null)} /> : null}
    </div>
  );
}

function TypingNames({ userIds }: { userIds: string[] }) {
  return (
    <span style={{ color: "var(--accent)" }}>
      {userIds.map((userId, index) => (
        <TypingUser key={userId} userId={userId} comma={index > 0} />
      ))}{" "}
      печатает…
    </span>
  );
}

function TypingUser({ userId, comma }: { userId: string; comma: boolean }) {
  const user = useUser(userId);
  return <>{(comma ? ", " : "") + (user.data?.full_name || "кто-то")}</>;
}

function DirectPresence({ userId }: { userId: string | null }) {
  const presence = useUiStore((state) => (userId ? state.presence[userId] : undefined));
  if (!userId) return <span>личный чат</span>;
  return <span>{presence?.online ? "в сети" : "не в сети"}</span>;
}

async function jumpToSeq(qc: ReturnType<typeof useQueryClient>, chatId: string, seq: number) {
  try {
    const page = await messagesApi.list(chatId, { after_seq: Math.max(0, seq - 21), limit: 50 });
    const data: InfiniteData<MessagesPage> = {
      pages: [{ items: page.items, has_more: page.has_more, next_before_seq: page.next_before_seq }],
      pageParams: [undefined],
    };
    qc.setQueryData<InfiniteData<MessagesPage>>(messagesKey(chatId), data);
    requestAnimationFrame(() => {
      document.querySelector(`[data-seq="${seq}"]`)?.scrollIntoView({ block: "center" });
    });
  } catch {
    return;
  }
}
