import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { usersApi } from "../../api/endpoints";
import type { User } from "../../api/types";
import { Avatar, Button, Input, Modal } from "../../components/ui";
import { useCreateChat } from "./queries";
import { toastError } from "../../stores/ui";
import { appNavigate } from "../../realtime/navigator";

export function NewChatDialog({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<"direct" | "group">("direct");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Record<string, User>>({});
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);

  const search = useQuery({
    queryKey: ["users-search", query],
    queryFn: () => usersApi.search(query, 20, 0),
    enabled: query.trim().length >= 1,
    staleTime: 30_000,
  });

  const users = useMemo(() => (query.trim() ? search.data?.items || [] : []), [query, search.data]);

  const create = useCreateChat((chat) => {
    onClose();
    appNavigate(`/chat/${chat.id}`);
  });

  const openDirect = async (user: User) => {
    setCreating(true);
    try {
      await create.mutateAsync({ type: "direct", user_id: user.id });
    } catch (error) {
      toastError(error, "Не удалось создать чат");
    } finally {
      setCreating(false);
    }
  };

  const createGroup = async () => {
    if (!title.trim()) return;
    setCreating(true);
    try {
      await create.mutateAsync({
        type: "group",
        title: title.trim(),
        member_ids: Object.keys(selected),
      });
    } catch (error) {
      toastError(error, "Не удалось создать группу");
    } finally {
      setCreating(false);
    }
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <Modal
      title={tab === "direct" ? "Новый личный чат" : "Новая группа"}
      onClose={onClose}
      footer={
        tab === "group" ? (
          <>
            <Button onClick={onClose}>Отмена</Button>
            <Button variant="primary" disabled={!title.trim() || creating} onClick={() => void createGroup()}>
              {creating ? "Создание…" : "Создать группу"}
            </Button>
          </>
        ) : undefined
      }
    >
      <div className="tabs">
        <button className={`tab${tab === "direct" ? " active" : ""}`} onClick={() => setTab("direct")}>
          Личный чат
        </button>
        <button className={`tab${tab === "group" ? " active" : ""}`} onClick={() => setTab("group")}>
          Группа
        </button>
      </div>

      {tab === "group" ? (
        <div className="field">
          <label>Название группы</label>
          <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Название" maxLength={200} />
          {Object.keys(selected).length ? (
            <div style={{ marginTop: 8, fontSize: 13, color: "var(--text-2)" }}>
              Выбрано участников: {Object.keys(selected).length}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="field">
        <label>Поиск сотрудников</label>
        <Input
          autoFocus
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Имя или логин…"
          maxLength={100}
        />
      </div>

      <div style={{ maxHeight: 320, overflowY: "auto" }}>
        {search.isFetching ? (
          <div className="center-note">Поиск…</div>
        ) : !query.trim() ? (
          <div className="center-note">Введите имя или логин</div>
        ) : users.length === 0 ? (
          <div className="center-note">Ничего не найдено</div>
        ) : (
          users.map((user) => {
            const isSelected = !!selected[user.id];
            return (
              <button
                key={user.id}
                className="search-result-item"
                onClick={() => {
                  if (tab === "direct") {
                    if (!creating) void openDirect(user);
                  } else {
                    setSelected((prev) => {
                      const next = { ...prev };
                      if (next[user.id]) delete next[user.id];
                      else next[user.id] = user;
                      return next;
                    });
                  }
                }}
              >
                <Avatar name={user.full_name} url={user.avatar_url} seed={user.id} size={36} />
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: "block", fontWeight: 600 }}>{user.full_name}</span>
                  <span style={{ display: "block", fontSize: 12.5, color: "var(--text-3)" }}>
                    @{user.username}
                    {user.title ? ` · ${user.title}` : ""}
                  </span>
                </span>
                {tab === "group" && isSelected ? <span className="badge">✓</span> : null}
              </button>
            );
          })
        )}
      </div>
    </Modal>
  );
}
