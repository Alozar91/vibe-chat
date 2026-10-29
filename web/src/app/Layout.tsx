import { useEffect, useMemo, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { Avatar, Button } from "../components/ui";
import { Toasts } from "../components/Toasts";
import { Lightbox } from "../components/Lightbox";
import { useRealtime } from "../realtime/useRealtime";
import { useUiStore } from "../stores/ui";
import { ChatList, useTotalUnread } from "../features/chats/ChatList";
import { NewChatDialog } from "../features/chats/NewChatDialog";
import { SearchDialog, useGlobalSearchHotkey } from "../features/search/SearchDialog";
import { useMe, isAdmin } from "../features/auth/queries";
import { appNavigate, registerNavigate } from "../realtime/navigator";

export function Layout() {
  const location = useLocation();
  const navigate = useNavigate();
  const me = useMe();
  const [newChatOpen, setNewChatOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  useGlobalSearchHotkey(() => setSearchOpen(true));
  useRealtime();
  useUnreadBadge();

  useEffect(() => {
    registerNavigate(navigate);
    return () => registerNavigate(null);
  }, [navigate]);

  const isDetail = /^\/(chat|admin|me|settings)/.test(location.pathname);

  const activeChatId = useMemo(() => {
    const match = /^\/chat\/([0-9a-fA-F-]{8,})/.exec(location.pathname);
    return match ? match[1] : null;
  }, [location.pathname]);

  return (
    <div className={`app-shell${isDetail ? " has-detail" : ""}`}>
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-brand">
            <img src="/favicon.svg" alt="" />
            <span>Вайб.Chat</span>
          </div>
          <div className="sidebar-actions">
            <Button variant="primary" onClick={() => setNewChatOpen(true)}>
              Написать
            </Button>
            <Button onClick={() => setSearchOpen(true)} title="Поиск (Ctrl+K)">
              🔍
            </Button>
          </div>
        </div>

        <ChatList activeChatId={activeChatId} />

        <div className="sidebar-footer">
          <button className="sidebar-me" onClick={() => appNavigate("/me")} title="Профиль">
            <Avatar name={me.data?.full_name || "?"} url={me.data?.avatar_url} seed={me.data?.id || "me"} size={38} />
            <span className="sidebar-me-name">
              <span className="name">{me.data?.full_name}</span>
              <span className="sub">@{me.data?.username}</span>
            </span>
          </button>
          <WsIndicator />
          <Button
            variant="ghost"
            className="icon"
            title="Настройки"
            onClick={() => appNavigate("/settings")}
          >
            ⚙
          </Button>
          {isAdmin(me.data) ? (
            <Button variant="ghost" className="icon" title="Администрирование" onClick={() => appNavigate("/admin")}>
              🛡
            </Button>
          ) : null}
        </div>
      </aside>

      <main className="content">
        <Outlet />
      </main>

      {newChatOpen ? <NewChatDialog onClose={() => setNewChatOpen(false)} /> : null}
      {searchOpen ? <SearchDialog onClose={() => setSearchOpen(false)} /> : null}
      <Toasts />
      <Lightbox />
    </div>
  );
}

function WsIndicator() {
  const status = useUiStore((state) => state.wsStatus);
  return <span className={`ws-dot ${status}`} title={status === "online" ? "Реальное время активно" : "Нет связи"} />;
}

function useUnreadBadge() {
  const total = useTotalUnread();
  useEffect(() => {
    document.title = total > 0 ? `(${total}) Вайб.Chat` : "Вайб.Chat";
    const nav = navigator as Navigator & {
      setAppBadge?: (count: number) => void;
      clearAppBadge?: () => void;
    };
    try {
      if (typeof nav.setAppBadge === "function") {
        if (total > 0) nav.setAppBadge(total);
        else if (typeof nav.clearAppBadge === "function") nav.clearAppBadge();
      }
    } catch {
      return;
    }
  }, [total]);
}
