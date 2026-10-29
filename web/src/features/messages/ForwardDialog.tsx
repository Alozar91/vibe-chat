import { useMemo, useState } from "react";
import { messagesApi } from "../../api/endpoints";
import type { Message } from "../../api/types";
import { Avatar, Button, Modal, Spinner } from "../../components/ui";
import { chatTitle } from "../chats/ChatList";
import { useChats, touchChatLastMessage } from "../chats/queries";
import { useToastStore, toastError } from "../../stores/ui";
import { ws } from "../../realtime/ws";
import { useQueryClient } from "@tanstack/react-query";

export function ForwardDialog({ message, onClose }: { message: Message; onClose: () => void }) {
  const qc = useQueryClient();
  const chatsQuery = useChats();
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(0);

  const chats = useMemo(() => {
    if (!chatsQuery.data) return [];
    return chatsQuery.data.pages.flatMap((page) => page.items).filter((chat) => chat.id !== message.chat_id);
  }, [chatsQuery.data, message.chat_id]);

  const forward = async () => {
    const targets = Object.keys(selected).filter((id) => selected[id]);
    if (!targets.length) return;
    setSending(true);
    let success = 0;
    for (const chatId of targets) {
      try {
        const created = await messagesApi.send(
          chatId,
          { body: "", forward: [{ chat_id: message.chat_id, seq: message.seq }] },
          crypto.randomUUID().replace(/-/g, ""),
        );
        success += 1;
        setDone(success);
        touchChatLastMessage(qc, chatId, created.seq, created.created_at);
      } catch (error) {
        toastError(error, `Не удалось переслать в чат`);
      }
    }
    setSending(false);
    ws.sendSubscribeRefresh();
    useToastStore.getState().push({
      kind: success ? "success" : "error",
      title: `Переслано в ${success} из ${targets.length} чатов`,
    });
    if (success) onClose();
  };

  return (
    <Modal
      title="Переслать сообщение"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" disabled={sending || !Object.values(selected).some(Boolean)} onClick={() => void forward()}>
            {sending ? `Отправка (${done})…` : "Переслать"}
          </Button>
        </>
      }
    >
      {chatsQuery.isPending ? (
        <Spinner />
      ) : chats.length === 0 ? (
        <div className="center-note">Нет других чатов</div>
      ) : (
        <div style={{ maxHeight: 340, overflowY: "auto" }}>
          {chats.map((chat) => (
            <button
              key={chat.id}
              className="search-result-item"
              onClick={() => setSelected((prev) => ({ ...prev, [chat.id]: !prev[chat.id] }))}
            >
              <Avatar name={chatTitle(chat)} url={chat.type === "direct" ? chat.counterpart?.avatar_url : chat.avatar_url} seed={chat.id} size={32} />
              <span style={{ flex: 1, fontWeight: 600 }}>{chatTitle(chat)}</span>
              {selected[chat.id] ? <span className="badge">✓</span> : null}
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
}
