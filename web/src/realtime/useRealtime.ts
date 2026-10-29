import { useEffect } from "react";
import { useMe } from "../features/auth/queries";
import { useUiStore } from "../stores/ui";
import { handleEvent } from "./events";
import { ws } from "./ws";

export function useRealtime() {
  const me = useMe();
  const meId = me.data?.id;

  useEffect(() => {
    if (!meId) return;
    ws.setHandler(handleEvent);
    ws.connect();
    const onOnline = () => ws.connect();
    window.addEventListener("online", onOnline);
    const prune = window.setInterval(() => useUiStore.getState().pruneTyping(), 1000);
    return () => {
      window.removeEventListener("online", onOnline);
      window.clearInterval(prune);
      ws.disconnect();
    };
  }, [meId]);
}
