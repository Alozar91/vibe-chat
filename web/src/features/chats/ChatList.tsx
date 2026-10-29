import { useMemo } from "react";
import type { QueryClient } from "@tanstack/react-query";
import { useChats, chatsFromCache } from "./queries";
import { usePreviewStore } from "../../stores/preview";
import { formatListTime } from "../../lib/time";
import { Avatar, Badge, Spinner } from "../../components/ui";
import { appNavigate } from "../../realtime/navigator";
import type { Chat } from "../../api/types";

export function chatTitle(chat: Chat): string {
  if (chat.type === "direct") {
    return chat.counterpart?.full_name || "Личный чат";
  }
  return chat.title || "Группа";
}

export function ChatList({ activeChatId, onOpen }: { activeChatId: string | null; onOpen?: (chatId: string) => void }) {
  const query = useChats();
  const previews = usePreviewStore((state) => state.previews);

  const chats = useMemo(() => {
    if (!query.data) return [];
    return query.data.pages.flatMap((page) => page.items);
  }, [query.data]);

  if (query.isPending) {
    return (
      <div style={{ padding: 30 }}>
        <Spinner />
      </div>
    );
  }

  if (query.isError) {
    return <div className="center-note">Не удалось загрузить чаты</div>;
  }

  if (!chats.length) {
    return <div className="center-note">Нет чатов. Нажмите «Написать», чтобы начать общение.</div>;
  }

  return (
    <div className="chat-list">
      {chats.map((chat) => (
        <ChatListItem
          key={chat.id}
          chat={chat}
          active={chat.id === activeChatId}
          preview={previews[chat.id]}
          onOpen={() => {
            onOpen?.(chat.id);
            appNavigate(`/chat/${chat.id}`);
          }}
        />
      ))}
      {query.hasNextPage ? (
        <div style={{ padding: 10, textAlign: "center" }}>
          <button className="btn sm" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
            {query.isFetchingNextPage ? "Загрузка…" : "Показать ещё"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function ChatListItem({
  chat,
  active,
  preview,
  onOpen,
}: {
  chat: Chat;
  active: boolean;
  preview?: { text: string; at: string };
  onOpen: () => void;
}) {
  const title = chatTitle(chat);
  return (
    <button className={`chat-item${active ? " active" : ""}`} onClick={onOpen}>
      <Avatar name={title} url={chat.type === "direct" ? chat.counterpart?.avatar_url : chat.avatar_url} seed={chat.id} size={42} />
      <span className="chat-item-main">
        <span className="chat-item-top">
          <span className="chat-item-title">{title}</span>
          <span className="chat-item-time">{formatListTime(preview?.at || chat.last_message_at)}</span>
        </span>
        <span className="chat-item-bottom">
          <span className="chat-item-preview">{preview?.text || ""}</span>
          <Badge value={chat.unread} />
        </span>
      </span>
    </button>
  );
}

export function useTotalUnread(): number {
  const query = useChats();
  const chats = useMemo(() => {
    if (!query.data) return [];
    return query.data.pages.flatMap((page) => page.items);
  }, [query.data]);
  return chats.reduce((sum, chat) => sum + chat.unread, 0);
}

export function totalUnreadFromCache(qc: QueryClient): number {
  return chatsFromCache(qc).reduce((sum, chat) => sum + chat.unread, 0);
}
