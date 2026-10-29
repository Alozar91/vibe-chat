import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { chatsApi, usersApi } from "../../api/endpoints";
import type { Chat } from "../../api/types";
import { Avatar, Button, Input, Modal, Pill, Spinner } from "../../components/ui";
import { useChatMembers, flattenMembers, useLeaveChat, useDeleteChat } from "./queries";
import { chatTitle } from "./ChatList";
import { useMe } from "../auth/queries";
import { toastError, useToastStore } from "../../stores/ui";
import { formatDateTime } from "../../lib/time";
import { appNavigate } from "../../realtime/navigator";

export function ChatInfoPanel({ chat, onClose }: { chat: Chat; onClose: () => void }) {
  const me = useMe();
  const qc = useQueryClient();
  const members = useChatMembers(chat.id);
  const invites = useQuery({
    queryKey: ["chat", chat.id, "invites"],
    queryFn: () => chatsApi.invites(chat.id),
    enabled: chat.type === "group" && (chat.my_role === "owner" || chat.my_role === "admin"),
  });
  const [showInviteForm, setShowInviteForm] = useState(false);
  const [addUsersOpen, setAddUsersOpen] = useState(false);
  const leave = useLeaveChat();
  const remove = useDeleteChat();
  const isGroup = chat.type === "group";
  const canManage = isGroup && (chat.my_role === "owner" || chat.my_role === "admin");
  const whoCanAdd = (chat.settings?.who_can_add_members as string) || "admins";
  const canAddMembers = isGroup && (canManage || whoCanAdd === "all");

  const [notifMode, setNotifMode] = useState<string>("all");

  const updateMembership = async (payload: { notifications?: string; muted_until?: string | null }) => {
    try {
      const result = await chatsApi.updateMyMembership(chat.id, payload);
      setNotifMode(result.notifications || "all");
      void qc.invalidateQueries({ queryKey: ["chat", chat.id] });
      void qc.invalidateQueries({ queryKey: ["chats"] });
      useToastStore.getState().push({ kind: "success", title: "Настройки чата обновлены" });
    } catch (error) {
      toastError(error, "Не удалось обновить настройки");
    }
  };

  return (
    <div className="info-panel">
      <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
        <h3 style={{ margin: 0, flex: 1 }}>{chatTitle(chat)}</h3>
        <Button variant="ghost" onClick={onClose} aria-label="Закрыть панель">
          ✕
        </Button>
      </div>

      {chat.description ? <p style={{ color: "var(--text-2)", fontSize: 13.5 }}>{chat.description}</p> : null}

      <div className="info-section">
        <h4>Мои настройки</h4>
        <div className="field">
          <label>Уведомления</label>
          <select
            className="select"
            value={chat.muted_until ? "muted" : notifMode}
            onChange={(event) => {
              const value = event.target.value;
              if (value === "muted") {
                void updateMembership({ muted_until: new Date(Date.now() + 8 * 3600_000).toISOString() });
              } else {
                void updateMembership({ muted_until: null, notifications: value });
              }
            }}
          >
            <option value="all">Все сообщения</option>
            <option value="mentions">Только упоминания</option>
            <option value="none">Без звука/уведомлений</option>
            <option value="muted">Заглушить на 8 часов</option>
          </select>
        </div>
        {chat.muted_until ? (
          <div style={{ fontSize: 12.5, color: "var(--text-3)" }}>
            Заглушено до {formatDateTime(chat.muted_until)}
          </div>
        ) : null}
      </div>

      <div className="info-section">
        <h4>Участники · {chat.members_count}</h4>
        {members.isPending ? (
          <Spinner />
        ) : (
          <>
            {flattenMembers(members.data).map((entry) => (
              <div key={entry.user.id} className="member-row">
                <Avatar name={entry.user.full_name} url={entry.user.avatar_url} seed={entry.user.id} size={30} />
                <span className="m-name">
                  {entry.user.full_name}
                  {entry.user.id === me.data?.id ? " (вы)" : ""}
                </span>
                {entry.role !== "member" ? <Pill>{entry.role === "owner" ? "владелец" : "админ"}</Pill> : null}
              </div>
            ))}
            {members.hasNextPage ? (
              <Button className="sm" disabled={members.isFetchingNextPage} onClick={() => void members.fetchNextPage()}>
                Ещё
              </Button>
            ) : null}
          </>
        )}
        {canAddMembers ? (
          <div style={{ marginTop: 8 }}>
            <Button className="sm" onClick={() => setAddUsersOpen(true)}>
              + Добавить участников
            </Button>
          </div>
        ) : null}
      </div>

      {canManage ? (
        <div className="info-section">
          <h4>Приглашения-ссылки</h4>
          {invites.data?.items.length ? (
            invites.data.items.map((invite) => (
              <div key={invite.id} className="invite-row">
                <code>{invite.url}</code>
                <Button
                  variant="ghost"
                  className="sm"
                  onClick={() => {
                    void navigator.clipboard.writeText(invite.url);
                    useToastStore.getState().push({ kind: "success", title: "Ссылка скопирована" });
                  }}
                >
                  Копировать
                </Button>
                <Button
                  variant="ghost"
                  className="sm danger"
                  onClick={async () => {
                    try {
                      await chatsApi.revokeInvite(chat.id, invite.id);
                      void qc.invalidateQueries({ queryKey: ["chat", chat.id, "invites"] });
                    } catch (error) {
                      toastError(error, "Не удалось отозвать ссылку");
                    }
                  }}
                >
                  Отозвать
                </Button>
              </div>
            ))
          ) : (
            <div style={{ fontSize: 13, color: "var(--text-3)" }}>Нет активных ссылок</div>
          )}
          <div style={{ marginTop: 8 }}>
            <Button className="sm" onClick={() => setShowInviteForm(true)}>
              + Создать ссылку
            </Button>
          </div>
        </div>
      ) : null}

      <div className="info-section">
        <h4>Действия</h4>
        <div className="row-actions">
          <Button
            variant="danger"
            onClick={() => {
              if (window.confirm(isGroup ? "Покинуть чат?" : "Удалить чат (скрыть переписку)?")) {
                if (isGroup) leave.mutate(chat.id);
                else remove.mutate(chat.id);
                onClose();
                appNavigate("/");
              }
            }}
          >
            {isGroup ? "Покинуть чат" : "Удалить чат"}
          </Button>
          {chat.my_role === "owner" ? (
            <Button
              variant="danger"
              onClick={() => {
                if (window.confirm("Удалить чат для всех участников?")) {
                  remove.mutate(chat.id);
                  onClose();
                  appNavigate("/");
                }
              }}
            >
              Удалить для всех
            </Button>
          ) : null}
        </div>
      </div>

      {addUsersOpen ? (
        <AddMembersDialog chat={chat} onClose={() => setAddUsersOpen(false)} />
      ) : null}
      {showInviteForm ? (
        <InviteFormDialog chat={chat} onClose={() => setShowInviteForm(false)} />
      ) : null}
    </div>
  );
}

function AddMembersDialog({ chat, onClose }: { chat: Chat; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const qc = useQueryClient();
  const search = useQuery({
    queryKey: ["users-search", query],
    queryFn: () => usersApi.search(query, 20, 0),
    enabled: query.trim().length >= 1,
  });
  const members = useChatMembers(chat.id);
  const memberIds = new Set(flattenMembers(members.data).map((entry) => entry.user.id));

  const add = async (user: { id: string }) => {
    setAdding(true);
    try {
      await chatsApi.addMembers(chat.id, [user.id]);
      void qc.invalidateQueries({ queryKey: ["chat", chat.id, "members"] });
      void qc.invalidateQueries({ queryKey: ["chat", chat.id] });
      useToastStore.getState().push({ kind: "success", title: "Участник добавлен" });
      onClose();
    } catch (error) {
      toastError(error, "Не удалось добавить участника");
    } finally {
      setAdding(false);
    }
  };

  return (
    <Modal title="Добавить участников" onClose={onClose}>
      <Input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Имя или логин…" />
      <div style={{ maxHeight: 300, overflowY: "auto", marginTop: 10 }}>
        {(search.data?.items || []).map((user) =>
          memberIds.has(user.id) ? null : (
            <button key={user.id} className="search-result-item" disabled={adding} onClick={() => void add(user)}>
              <Avatar name={user.full_name} url={user.avatar_url} seed={user.id} size={32} />
              <span style={{ flex: 1, fontWeight: 600 }}>{user.full_name}</span>
              <span style={{ fontSize: 12.5, color: "var(--text-3)" }}>@{user.username}</span>
            </button>
          ),
        )}
        {!query.trim() ? <div className="center-note">Введите имя для поиска</div> : null}
      </div>
    </Modal>
  );
}

function InviteFormDialog({ chat, onClose }: { chat: Chat; onClose: () => void }) {
  const [maxUses, setMaxUses] = useState("");
  const [hours, setHours] = useState("");
  const [creating, setCreating] = useState(false);
  const qc = useQueryClient();

  const create = async () => {
    setCreating(true);
    try {
      const invite = await chatsApi.createInvite(chat.id, {
        max_uses: maxUses ? Number(maxUses) : null,
        expires_at: hours ? new Date(Date.now() + Number(hours) * 3600_000).toISOString() : null,
      });
      await navigator.clipboard.writeText(invite.url).catch(() => undefined);
      void qc.invalidateQueries({ queryKey: ["chat", chat.id, "invites"] });
      useToastStore.getState().push({ kind: "success", title: "Ссылка создана и скопирована" });
      onClose();
    } catch (error) {
      toastError(error, "Не удалось создать ссылку");
    } finally {
      setCreating(false);
    }
  };

  return (
    <Modal
      title="Новое приглашение"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={creating} onClick={() => void create()}>
            Создать
          </Button>
        </>
      }
    >
      <div className="field">
        <label>Лимит использований (пусто — без лимита)</label>
        <Input type="number" min={1} value={maxUses} onChange={(event) => setMaxUses(event.target.value)} />
      </div>
      <div className="field">
        <label>Срок действия, часов (пусто — бессрочно)</label>
        <Input type="number" min={1} value={hours} onChange={(event) => setHours(event.target.value)} />
      </div>
    </Modal>
  );
}
