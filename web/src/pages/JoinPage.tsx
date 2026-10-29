import { useEffect, useRef } from "react";
import { useParams } from "react-router-dom";
import { Button, Spinner } from "../components/ui";
import { useJoinChat } from "../features/chats/queries";
import { appNavigate } from "../realtime/navigator";
import { ApiError } from "../api/client";

const MESSAGES: Record<number, string> = {
  404: "Приглашение не найдено",
  410: "Срок действия приглашения истёк или оно отозвано",
  429: "Лимит использований приглашения исчерпан",
};

export function JoinPage() {
  const { code } = useParams<{ code: string }>();
  const join = useJoinChat((chat) => appNavigate(`/chat/${chat.id}`));
  const started = useRef(false);

  useEffect(() => {
    if (code && !started.current) {
      started.current = true;
      join.mutate(code);
    }
  }, [code, join]);

  if (join.isPending && !join.error) {
    return (
      <div className="page" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center" }}>
          <Spinner />
          <p style={{ color: "var(--text-3)" }}>Присоединяемся к чату…</p>
        </div>
      </div>
    );
  }

  if (join.isError) {
    const error = join.error;
    return (
      <div className="page" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center" }}>
          <p style={{ fontSize: 17, fontWeight: 700 }}>
            {error instanceof ApiError && MESSAGES[error.status] ? MESSAGES[error.status] : "Не удалось присоединиться к чату"}
          </p>
          <p style={{ color: "var(--text-3)" }}>{error instanceof Error ? error.message : ""}</p>
          <Button onClick={() => appNavigate("/")}>На главную</Button>
        </div>
      </div>
    );
  }

  return null;
}
