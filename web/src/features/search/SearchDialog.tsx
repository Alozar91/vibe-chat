import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { searchApi, type SearchParams } from "../../api/endpoints";
import type { SearchItem } from "../../api/types";
import { Avatar, Input, Modal, Spinner } from "../../components/ui";
import { appNavigate } from "../../realtime/navigator";
import { useCreateChat } from "../chats/queries";
import { plainPreview } from "../../lib/markdown";
import { formatDateTime } from "../../lib/time";

export function SearchDialog({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<SearchParams["type"]>("messages");
  const debounceRef = useRef<number | null>(null);
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => setDebounced(query.trim()), 300);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [query]);

  const search = useQuery({
    queryKey: ["search", tab, debounced],
    queryFn: () => searchApi.search({ q: debounced, type: tab, limit: 20 }),
    enabled: debounced.length >= 1,
    staleTime: 30_000,
  });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const items = search.data?.items || [];

  return (
    <Modal title="Поиск" onClose={onClose} wide>
      <Input
        autoFocus
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Поиск по сообщениям, чатам и людям…"
        maxLength={200}
      />
      <div className="tabs" style={{ marginTop: 12 }}>
        {(["messages", "chats", "users"] as const).map((value) => (
          <button key={value} className={`tab${tab === value ? " active" : ""}`} onClick={() => setTab(value)}>
            {value === "messages" ? "Сообщения" : value === "chats" ? "Чаты" : "Люди"}
          </button>
        ))}
      </div>

      <div style={{ maxHeight: 380, overflowY: "auto" }}>
        {search.isFetching ? (
          <div style={{ padding: 20 }}>
            <Spinner />
          </div>
        ) : !debounced ? (
          <div className="center-note">Введите запрос</div>
        ) : !items.length ? (
          <div className="center-note">Ничего не найдено</div>
        ) : (
          items.map((item, index) => (
            <SearchResultRow key={index} item={item} onClose={onClose} />
          ))
        )}
      </div>
    </Modal>
  );
}

function SearchResultRow({ item, onClose }: { item: SearchItem; onClose: () => void }) {
  const createChat = useCreateChat((chat) => {
    onClose();
    appNavigate(`/chat/${chat.id}`);
  });

  if (item.type === "message") {
    return (
      <button
        className="search-result-item"
        onClick={() => {
          onClose();
          appNavigate(`/chat/${item.chat_id}?m=${item.seq}`);
        }}
      >
        <span style={{ flex: 1, minWidth: 0 }}>
          <span className="sr-context">{plainPreview(item.message.body) || "(вложение)"}</span>
          <span className="sr-chat">{formatDateTime(item.message.created_at)}</span>
        </span>
      </button>
    );
  }

  if (item.type === "chat") {
    return (
      <button
        className="search-result-item"
        onClick={() => {
          onClose();
          appNavigate(`/chat/${item.chat.id}`);
        }}
      >
        <Avatar name={item.chat.title || "Группа"} seed={item.chat.id} size={32} />
        <span style={{ flex: 1, fontWeight: 600 }}>{item.chat.title || "Группа"}</span>
      </button>
    );
  }

  return (
    <button
      className="search-result-item"
      onClick={() => {
        if (!createChat.isPending) {
          void createChat.mutateAsync({ type: "direct", user_id: item.user.id });
        }
      }}
    >
      <Avatar name={item.user.full_name} url={item.user.avatar_url} seed={item.user.id} size={32} />
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ display: "block", fontWeight: 600 }}>{item.user.full_name}</span>
        <span style={{ display: "block", fontSize: 12.5, color: "var(--text-3)" }}>@{item.user.username}</span>
      </span>
    </button>
  );
}

export function useGlobalSearchHotkey(onOpen: () => void) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        onOpen();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onOpen]);
}

export function searchTabsLabel(tab: SearchParams["type"]): string {
  const labels = { messages: "Сообщения", chats: "Чаты", users: "Люди" };
  return labels[tab];
}
