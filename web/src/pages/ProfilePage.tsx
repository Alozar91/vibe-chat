import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { authApi, meApi } from "../api/endpoints";
import type { User } from "../api/types";
import { Avatar, Button, Field, Input, PageBack, Select, Spinner } from "../components/ui";
import { useMe, useSessions } from "../features/auth/queries";
import { toastError, useToastStore } from "../stores/ui";
import { appNavigate } from "../realtime/navigator";
import { queryClient } from "../app/query";
import { formatDateTime } from "../lib/time";
import { enableWebPush, pushStatus } from "../features/notifications/push";

export function ProfilePage() {
  const me = useMe();
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [title, setTitle] = useState("");
  const [loadedFor, setLoadedFor] = useState<string | null>(null);

  useEffect(() => {
    if (!me.data || loadedFor === me.data.id) return;
    setFullName(me.data.full_name || "");
    setPhone(me.data.phone || "");
    setTitle(me.data.title || "");
    setLoadedFor(me.data.id);
  }, [me.data, loadedFor]);

  const update = useMutation({
    mutationFn: (payload: Parameters<typeof meApi.update>[0]) => meApi.update(payload),
    onSuccess: (user: User) => {
      queryClient.setQueryData(["me"], user);
      useToastStore.getState().push({ kind: "success", title: "Профиль сохранён" });
    },
    onError: (error) => toastError(error, "Не удалось сохранить профиль"),
  });

  if (me.isPending) {
    return (
      <div className="page">
        <Spinner />
      </div>
    );
  }
  if (me.isError || !me.data) {
    return <div className="page">Не удалось загрузить профиль</div>;
  }

  const user = me.data;
  const ns = user.notification_settings || {};
  const dndUntil = typeof ns.dnd_until === "string" ? ns.dnd_until.slice(0, 16) : "";
  const keycloakAccountUrl = (import.meta.env.VITE_KEYCLOAK_URL || "http://localhost:8081") + "/realms/messenger/account";

  return (
    <div className="page">
      <div className="page-narrow">
        <PageBack />
        <h2>Профиль</h2>

        <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 20 }}>
          <Avatar name={user.full_name} url={user.avatar_url} seed={user.id} size={64} />
          <div>
            <div style={{ fontWeight: 700, fontSize: 17 }}>{user.full_name}</div>
            <div style={{ color: "var(--text-3)", fontSize: 13 }}>@{user.username}</div>
            <div style={{ marginTop: 4, display: "flex", gap: 6 }}>
              <span className="pill">{user.source || "local"}</span>
              <span className="pill">{user.role || "member"}</span>
            </div>
          </div>
        </div>

        <Field label="Полное имя">
          <Input value={fullName} maxLength={200} onChange={(event) => setFullName(event.target.value)} />
        </Field>
        <Field label="Должность">
          <Input value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} />
        </Field>
        <Field label="Телефон">
          <Input value={phone} maxLength={32} onChange={(event) => setPhone(event.target.value)} placeholder="+7…" />
        </Field>
        <div style={{ display: "flex", gap: 8, marginBottom: 24 }}>
          <Button
            variant="primary"
            disabled={update.isPending || fullName.trim().length === 0}
            onClick={() =>
              update.mutate({
                full_name: fullName.trim(),
                title: title.trim() || null,
                phone: phone.trim() || null,
              } as Parameters<typeof meApi.update>[0])
            }
          >
            {update.isPending ? "Сохранение…" : "Сохранить"}
          </Button>
        </div>

        <h2 style={{ fontSize: 16 }}>Уведомления</h2>
        <Field label="Режим по умолчанию">
          <Select
            value={String(ns.default_mode || "all")}
            onChange={(event) =>
              update.mutate({ notification_settings: { ...ns, default_mode: event.target.value } })
            }
          >
            <option value="all">Все сообщения</option>
            <option value="mentions">Только упоминания</option>
            <option value="none">Отключены</option>
          </Select>
        </Field>
        <Field label="Не беспокоить до">
          <Input
            type="datetime-local"
            value={dndUntil}
            onChange={(event) => {
              const value = event.target.value ? new Date(event.target.value).toISOString() : null;
              update.mutate({ notification_settings: { ...ns, dnd_until: value } });
            }}
          />
        </Field>

        <PushSection />

        <h2 style={{ fontSize: 16 }}>Активные сессии</h2>
        <SessionsList />

        <div style={{ display: "flex", gap: 8, marginTop: 20, flexWrap: "wrap" }}>
          <a className="btn" href={keycloakAccountUrl} target="_blank" rel="noopener noreferrer">
            Сменить пароль (Keycloak)
          </a>
          <Button
            variant="danger"
            onClick={async () => {
              try {
                await authApi.logout();
                queryClient.clear();
                appNavigate("/login");
              } catch (error) {
                toastError(error, "Не удалось выйти");
              }
            }}
          >
            Выйти
          </Button>
          <Button
            variant="danger"
            onClick={async () => {
              if (!window.confirm("Завершить все сессии на всех устройствах?")) return;
              try {
                await authApi.logoutAll();
                queryClient.clear();
                appNavigate("/login");
              } catch (error) {
                toastError(error, "Не удалось завершить сессии");
              }
            }}
          >
            Выйти на всех устройствах
          </Button>
        </div>
      </div>
    </div>
  );
}

function PushSection() {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(pushStatus());

  return (
    <div className="info-section" style={{ margin: "18px 0" }}>
      <h4>Web Push</h4>
      <div className="notification-row">
        <span>
          {status === "granted" ? "Подписка активна" : status === "denied" ? "Заблокировано в браузере" : status === "unsupported" ? "Не поддерживается" : "Не включено"}
        </span>
        {status !== "granted" && status !== "unsupported" ? (
          <Button
            className="sm"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              const result = await enableWebPush();
              setBusy(false);
              setStatus(pushStatus());
              if (!result.ok && result.reason) {
                useToastStore.getState().push({ kind: "error", title: "Web Push", body: result.reason });
              }
            }}
          >
            Включить
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function SessionsList() {
  const sessions = useSessions();
  const revoke = useMutation({
    mutationFn: (sessionId: string) => authApi.revokeSession(sessionId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["sessions"] }),
  });

  if (sessions.isPending) return <Spinner />;
  const items = sessions.data?.items || [];
  if (!items.length) return <div className="center-note">Нет активных сессий</div>;

  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Платформа</th>
            <th>IP</th>
            <th>Создана</th>
            <th>Активность</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((session) => (
            <tr key={session.id}>
              <td>
                {session.platform} {session.current ? <span className="pill green">текущая</span> : null}
              </td>
              <td className="mono">{session.ip || "—"}</td>
              <td>{formatDateTime(session.created_at)}</td>
              <td>{formatDateTime(session.last_seen_at)}</td>
              <td>
                <Button
                  variant="ghost"
                  className="sm danger"
                  disabled={revoke.isPending}
                  onClick={() => revoke.mutate(session.id)}
                >
                  Отозвать
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
