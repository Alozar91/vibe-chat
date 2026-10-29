import { useEffect } from "react";
import { Button, EmptyState } from "../components/ui";
import { ChatList } from "../features/chats/ChatList";
import { useChats } from "../features/chats/queries";
import { getLastChat } from "../lib/lastChat";
import { appNavigate } from "../realtime/navigator";

export function HomePage() {
  const chats = useChats();

  useEffect(() => {
    if (!chats.data) return;
    const items = chats.data.pages[0]?.items || [];
    if (!items.length) return;
    const last = getLastChat();
    if (last && items.some((chat) => chat.id === last)) {
      appNavigate(`/chat/${last}`);
      return;
    }
    appNavigate(`/chat/${items[0].id}`);
  }, [chats.data]);

  if (chats.isPending) {
    return <EmptyState title="Загрузка…" />;
  }

  if (!chats.data || !(chats.data.pages[0]?.items || []).length) {
    return (
      <EmptyState
        icon="💬"
        title="Нет чатов"
        hint="Нажмите «Написать» слева, чтобы начать переписку с коллегой или создать группу."
      >
        <Button variant="primary" onClick={() => appNavigate("/me")}>
          Профиль
        </Button>
      </EmptyState>
    );
  }

  return (
    <div style={{ padding: 16, maxWidth: 520 }}>
      <h3 style={{ marginTop: 0 }}>Выберите чат</h3>
      <ChatList activeChatId={null} />
    </div>
  );
}
