import { redirectToLogin } from "../api/client";
import { randomId } from "../lib/format";
import { useUiStore } from "../stores/ui";
import { collectSyncChats } from "./snapshot";

const HEARTBEAT_MS = 30000;
const WATCHDOG_MS = 70000;
const MAX_BACKOFF_MS = 30000;
const RECONNECT_MAX_ATTEMPTS_BEFORE_AUTH_CHECK = 4;

type EventHandler = (type: string, data: Record<string, unknown>) => void;

class WsManager {
  private socket: WebSocket | null = null;
  private attempt = 0;
  private reconnectTimer: number | null = null;
  private heartbeatTimer: number | null = null;
  private watchdogTimer: number | null = null;
  private lastReceivedAt = 0;
  private closedByUs = false;
  private handler: EventHandler | null = null;
  private authCheckPending = false;

  setHandler(handler: EventHandler | null) {
    this.handler = handler;
  }

  connect() {
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this.closedByUs = false;
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${window.location.host}/ws`;
    useUiStore.getState().setWsStatus("connecting");
    let socket: WebSocket;
    try {
      socket = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      this.attempt = 0;
      this.authCheckPending = false;
      this.lastReceivedAt = Date.now();
      useUiStore.getState().setWsStatus("online");
      this.startTimers();
      this.requestSync(collectSyncChats());
    };

    socket.onmessage = (event) => {
      this.lastReceivedAt = Date.now();
      try {
        const frame = JSON.parse(event.data as string) as { type?: string; data?: Record<string, unknown> };
        if (!frame.type) return;
        if (frame.type === "pong") return;
        this.handler?.(frame.type, frame.data || {});
      } catch {
        return;
      }
    };

    socket.onclose = (event) => {
      this.stopTimers();
      this.socket = null;
      useUiStore.getState().setWsStatus("offline");
      if (event.code === 4401) {
        redirectToLogin();
        return;
      }
      if (!this.closedByUs) this.scheduleReconnect();
    };

    socket.onerror = () => {
      socket.close();
    };
  }

  disconnect() {
    this.closedByUs = true;
    this.stopTimers();
    this.clearReconnect();
    if (this.socket) {
      this.socket.close();
      this.socket = null;
    }
    useUiStore.getState().setWsStatus("offline");
  }

  private scheduleReconnect() {
    if (this.reconnectTimer !== null) return;
    const base = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** this.attempt);
    const jitter = base * (0.7 + Math.random() * 0.6);
    this.attempt += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      if (this.attempt > RECONNECT_MAX_ATTEMPTS_BEFORE_AUTH_CHECK && !this.authCheckPending) {
        this.authCheckPending = true;
        fetch("/v1/me", { credentials: "same-origin" })
          .then((response) => {
            this.authCheckPending = false;
            if (response.status === 401) redirectToLogin();
            else this.connect();
          })
          .catch(() => {
            this.authCheckPending = false;
            this.connect();
          });
        return;
      }
      this.connect();
    }, jitter);
  }

  private clearReconnect() {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private startTimers() {
    this.stopTimers();
    this.heartbeatTimer = window.setInterval(() => {
      this.send({ type: "ping" });
    }, HEARTBEAT_MS);
    this.watchdogTimer = window.setInterval(() => {
      if (Date.now() - this.lastReceivedAt > WATCHDOG_MS) {
        this.socket?.close();
      }
    }, 10000);
  }

  private stopTimers() {
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.watchdogTimer !== null) {
      window.clearInterval(this.watchdogTimer);
      this.watchdogTimer = null;
    }
  }

  send(payload: Record<string, unknown>): boolean {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload));
      return true;
    }
    return false;
  }

  requestSync(chats: { chat_id: string; last_seq: number }[]) {
    if (!chats.length) return;
    this.send({ type: "sync.request", chats: chats.slice(0, 100) });
  }

  sendSubscribeRefresh() {
    this.send({ type: "subscribe.refresh" });
  }

  sendTyping(chatId: string, start: boolean) {
    this.send({ type: start ? "typing.start" : "typing.stop", chat_id: chatId });
  }
}

export const ws = new WsManager();

export function newIdempotencyKey(): string {
  return randomId();
}
