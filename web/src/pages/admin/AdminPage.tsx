import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminApi } from "../../api/endpoints";
import type { User } from "../../api/types";
import { Avatar, Button, Field, Input, Modal, PageBack, Pill, Spinner } from "../../components/ui";
import { toastError, useToastStore } from "../../stores/ui";
import { formatBytes } from "../../lib/format";
import { formatDateTime } from "../../lib/time";
import { queryClient } from "../../app/query";

type Tab = "stats" | "users" | "audit" | "bots";

export function AdminPage() {
  const [tab, setTab] = useState<Tab>("stats");

  return (
    <div className="page">
      <div className="page-narrow" style={{ maxWidth: 980 }}>
        <PageBack />
        <h2>Администрирование</h2>
        <div className="tabs">
          <button className={`tab${tab === "stats" ? " active" : ""}`} onClick={() => setTab("stats")}>
            Обзор
          </button>
          <button className={`tab${tab === "users" ? " active" : ""}`} onClick={() => setTab("users")}>
            Пользователи
          </button>
          <button className={`tab${tab === "audit" ? " active" : ""}`} onClick={() => setTab("audit")}>
            Аудит
          </button>
          <button className={`tab${tab === "bots" ? " active" : ""}`} onClick={() => setTab("bots")}>
            Боты
          </button>
        </div>
        {tab === "stats" ? <StatsTab /> : null}
        {tab === "users" ? <UsersTab /> : null}
        {tab === "audit" ? <AuditTab /> : null}
        {tab === "bots" ? <BotsTab /> : null}
      </div>
    </div>
  );
}

function StatsTab() {
  const stats = useQuery({ queryKey: ["admin-stats"], queryFn: adminApi.stats, staleTime: 60_000 });
  if (stats.isPending) return <Spinner />;
  if (stats.isError || !stats.data) return <div className="center-note">Не удалось загрузить статистику</div>;
  const s = stats.data;
  return (
    <div className="cards">
      <div className="card">
        <div className="c-value">{s.dau}</div>
        <div className="c-label">Активны за сутки (DAU)</div>
      </div>
      <div className="card">
        <div className="c-value">{s.messages_per_day}</div>
        <div className="c-label">Сообщений за сутки</div>
      </div>
      <div className="card">
        <div className="c-value">{s.users_total}</div>
        <div className="c-label">Пользователей</div>
      </div>
      <div className="card">
        <div className="c-value">{s.chats_total}</div>
        <div className="c-label">Чатов</div>
      </div>
      <div className="card">
        <div className="c-value">{formatBytes(s.storage_bytes)}</div>
        <div className="c-label">Хранилище</div>
      </div>
    </div>
  );
}

function UsersTab() {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [tempPassword, setTempPassword] = useState<{ username: string; password: string } | null>(null);
  const [sessionsFor, setSessionsFor] = useState<User | null>(null);

  const users = useQuery({
    queryKey: ["admin-users", query, offset],
    queryFn: () => adminApi.users({ q: query || undefined, offset }),
    staleTime: 15_000,
  });

  const disable = useMutation({
    mutationFn: ({ userId, disable }: { userId: string; disable: boolean }) =>
      disable ? adminApi.disableUser(userId) : adminApi.enableUser(userId),
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      useToastStore.getState().push({
        kind: "success",
        title: user.status === "disabled" ? "Пользователь отключён" : "Пользователь включён",
      });
    },
    onError: (error) => toastError(error, "Не удалось изменить статус"),
  });

  const resetPassword = useMutation({
    mutationFn: (userId: string) => adminApi.resetPassword(userId, false),
    onSuccess: (result, userId) => {
      const user = users.data?.items.find((item) => item.id === userId);
      if (result.temporary_password) {
        setTempPassword({ username: user?.username || userId, password: result.temporary_password });
      } else {
        useToastStore.getState().push({ kind: "success", title: "Письмо со сбросом отправлено" });
      }
      void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error) => toastError(error, "Не удалось сбросить пароль"),
  });

  const importCsv = useMutation({
    mutationFn: (file: File) => adminApi.importCsv(file),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      useToastStore.getState().push({
        kind: result.failed.length ? "error" : "success",
        title: `Импорт: создано ${result.created}, ошибок ${result.failed.length}`,
        body: result.failed.slice(0, 5).map((f) => `строка ${f.row}: ${f.error}`).join("; ") || undefined,
      });
    },
    onError: (error) => toastError(error, "Ошибка импорта CSV"),
  });

  const items = users.data?.items || [];

  return (
    <div>
      <div className="toolbar">
        <Input
          style={{ maxWidth: 280 }}
          value={search}
          placeholder="Поиск по имени/логину…"
          onChange={(event) => setSearch(event.target.value)}
        />
        <Button onClick={() => { setOffset(0); setQuery(search.trim()); }}>Найти</Button>
        <span className="spacer" />
        <label className="btn">
          Импорт CSV
          <input
            type="file"
            accept=".csv,text/csv"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) importCsv.mutate(file);
              event.target.value = "";
            }}
          />
        </label>
        <Button variant="primary" onClick={() => setCreateOpen(true)}>
          + Пользователь
        </Button>
      </div>

      {users.isPending ? (
        <Spinner />
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Пользователь</th>
                <th>Роль</th>
                <th>Статус</th>
                <th>Последний вход</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {items.map((user) => (
                <tr key={user.id}>
                  <td>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <Avatar name={user.full_name} url={user.avatar_url} seed={user.id} size={30} />
                      <span>
                        <span style={{ display: "block", fontWeight: 600 }}>{user.full_name}</span>
                        <span style={{ display: "block", fontSize: 12, color: "var(--text-3)" }}>
                          @{user.username} {user.email ? `· ${user.email}` : ""}
                        </span>
                      </span>
                    </div>
                  </td>
                  <td>
                    <Pill tone={user.role === "member" ? undefined : "green"}>{user.role || "member"}</Pill>
                  </td>
                  <td>
                    <Pill tone={user.status === "active" ? "green" : "red"}>
                      {user.status === "active" ? "активен" : "отключён"}
                    </Pill>
                  </td>
                  <td>{user.last_login_at ? formatDateTime(user.last_login_at) : "—"}</td>
                  <td>
                    <div className="row-actions">
                      <Button className="sm" disabled={resetPassword.isPending} onClick={() => resetPassword.mutate(user.id)}>
                        Сброс пароля
                      </Button>
                      <Button className="sm" onClick={() => setSessionsFor(user)}>
                        Сессии
                      </Button>
                      {user.status === "active" ? (
                        <Button
                          variant="danger"
                          className="sm"
                          disabled={disable.isPending}
                          onClick={() => {
                            if (window.confirm(`Отключить пользователя ${user.username}?`)) {
                              disable.mutate({ userId: user.id, disable: true });
                            }
                          }}
                        >
                          Отключить
                        </Button>
                      ) : (
                        <Button className="sm" disabled={disable.isPending} onClick={() => disable.mutate({ userId: user.id, disable: false })}>
                          Включить
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {users.data?.next_offset ? (
        <div style={{ marginTop: 10 }}>
          <Button onClick={() => setOffset(users.data!.next_offset as number)}>Загрузить ещё</Button>
        </div>
      ) : null}

      {createOpen ? (
        <CreateUserDialog
          onClose={() => setCreateOpen(false)}
          onCreated={(result) => {
            setCreateOpen(false);
            void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
            if (result.temporary_password) {
              setTempPassword({ username: result.username, password: result.temporary_password });
            } else {
              useToastStore.getState().push({ kind: "success", title: "Пользователь создан, письмо отправлено" });
            }
          }}
        />
      ) : null}

      {tempPassword ? (
        <Modal title="Временный пароль" onClose={() => setTempPassword(null)}>
          <p>
            Пароль для <strong>@{tempPassword.username}</strong> показывается один раз:
          </p>
          <p className="mono" style={{ fontSize: 16, background: "var(--bg-panel-2)", padding: "10px 12px", borderRadius: 8 }}>
            {tempPassword.password}
          </p>
          <p style={{ color: "var(--text-3)", fontSize: 13 }}>
            Передайте его пользователю; при входе потребуется сменить пароль.
          </p>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <Button
              onClick={() => {
                void navigator.clipboard.writeText(tempPassword.password);
                useToastStore.getState().push({ kind: "success", title: "Скопировано" });
              }}
            >
              Копировать
            </Button>
            <Button variant="primary" onClick={() => setTempPassword(null)}>
              Готово
            </Button>
          </div>
        </Modal>
      ) : null}

      {sessionsFor ? <SessionsDialog user={sessionsFor} onClose={() => setSessionsFor(null)} /> : null}
    </div>
  );
}

function CreateUserDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (user: User & { temporary_password?: string }) => void }) {
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [sendEmail, setSendEmail] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setError(null);
    if (!/^[a-zA-Z0-9_.-]{2,64}$/.test(username)) {
      setError("Логин: 2–64 символа, латиница/цифры/._-");
      return;
    }
    if (!fullName.trim()) {
      setError("Укажите ФИО");
      return;
    }
    setBusy(true);
    try {
      const user = await adminApi.createUser({
        username,
        full_name: fullName.trim(),
        email: email.trim() || undefined,
        send_email: sendEmail && !!email.trim(),
      });
      onCreated(user);
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Ошибка создания");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Новый пользователь"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={busy} onClick={() => void create()}>
            {busy ? "Создание…" : "Создать"}
          </Button>
        </>
      }
    >
      <Field label="Логин">
        <Input value={username} onChange={(event) => setUsername(event.target.value)} autoFocus />
      </Field>
      <Field label="ФИО">
        <Input value={fullName} onChange={(event) => setFullName(event.target.value)} />
      </Field>
      <Field label="Email (для письма с паролем)">
        <Input type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
      </Field>
      <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 14 }}>
        <input type="checkbox" checked={sendEmail} onChange={(event) => setSendEmail(event.target.checked)} />
        Отправить письмо со ссылкой установки пароля
      </label>
      {error ? <div className="field-error">{error}</div> : null}
    </Modal>
  );
}

function SessionsDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const sessions = useQuery({
    queryKey: ["admin-sessions", user.id],
    queryFn: () => adminApi.userSessions(user.id),
  });
  const revoke = useMutation({
    mutationFn: (sessionId: string) => adminApi.revokeSession(sessionId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["admin-sessions", user.id] }),
  });

  return (
    <Modal title={`Сессии — ${user.username}`} onClose={onClose}>
      {sessions.isPending ? (
        <Spinner />
      ) : !(sessions.data?.items || []).length ? (
        <div className="center-note">Нет активных сессий</div>
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Платформа</th>
                <th>IP</th>
                <th>Активность</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(sessions.data?.items || []).map((session) => (
                <tr key={session.id}>
                  <td>{session.platform}</td>
                  <td className="mono">{session.ip || "—"}</td>
                  <td>{formatDateTime(session.last_seen_at)}</td>
                  <td>
                    <Button variant="ghost" className="sm danger" onClick={() => revoke.mutate(session.id)}>
                      Отозвать
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}

function AuditTab() {
  const [offset, setOffset] = useState(0);
  const audit = useQuery({
    queryKey: ["admin-audit", offset],
    queryFn: () => adminApi.audit({ offset }),
    staleTime: 15_000,
  });
  const items = useMemo(() => audit.data?.items || [], [audit.data]);

  if (audit.isPending) return <Spinner />;

  return (
    <div>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Время</th>
              <th>Действие</th>
              <th>Объект</th>
              <th>IP</th>
            </tr>
          </thead>
          <tbody>
            {items.map((entry) => (
              <tr key={entry.id}>
                <td style={{ whiteSpace: "nowrap" }}>{formatDateTime(entry.created_at)}</td>
                <td>
                  <span className="mono">{entry.action}</span>
                </td>
                <td>
                  {entry.entity_type ? `${entry.entity_type}:${entry.entity_id || ""}` : "—"}
                </td>
                <td className="mono">{entry.ip || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {audit.data?.next_offset ? (
        <div style={{ marginTop: 10 }}>
          <Button onClick={() => setOffset(audit.data!.next_offset as number)}>Загрузить ещё</Button>
        </div>
      ) : null}
    </div>
  );
}

function BotsTab() {
  const bots = useQuery({ queryKey: ["admin-bots"], queryFn: adminApi.bots, staleTime: 30_000 });
  const disable = useMutation({
    mutationFn: (botId: string) => adminApi.disableBot(botId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["admin-bots"] }),
  });

  if (bots.isPending) return <Spinner />;
  const items = bots.data?.items || [];
  if (!items.length) return <div className="center-note">Ботов нет</div>;

  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Бот</th>
            <th>Описание</th>
            <th>Статус</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((bot) => (
            <tr key={bot.user_id}>
              <td>
                <span style={{ display: "block", fontWeight: 600 }}>{bot.full_name}</span>
                <span style={{ display: "block", fontSize: 12, color: "var(--text-3)" }}>@{bot.username}</span>
              </td>
              <td>{bot.description || "—"}</td>
              <td>
                <Pill tone={bot.is_enabled ? "green" : "red"}>{bot.is_enabled ? "активен" : "отключён"}</Pill>
              </td>
              <td>
                {bot.is_enabled ? (
                  <Button variant="danger" className="sm" onClick={() => disable.mutate(bot.user_id)}>
                    Отключить
                  </Button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
