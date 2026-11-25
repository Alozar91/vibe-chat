/**
 * WS-client (Docs/android.md §3.3): синглтон, ticket-auth, автореконнект с
 * экспоненциальной задержкой + джиттер, одна точка диспетчеризации.
 * Client→server — только `typing` (§9 концепции); мутации через REST.
 */

import { config } from "./config";
import { apiClient } from "./api-client";
import { useSession } from "../stores/session";
import type { WsEnvelope } from "../api/types";

type Dispatch = (envelope: WsEnvelope) => void;

interface WsClient {
  /** Подключиться (ticket получает сам через POST /ws/ticket) */
  connect: () => Promise<void>;
  disconnect: () => void;
  sendTyping: (chatId: string) => void;
  onDispatch: (fn: Dispatch | null) => void;
  isConnected: () => boolean;
  /** Колбэк на переход connected/reconnecting — для UI-бания соединения */
  onConnectionChange: (fn: ((connected: boolean) => void) | null) => void;
}

let socket: WebSocket | null = null;
let dispatchFn: Dispatch | null = null;
let connectionChangeFn: ((connected: boolean) => void) | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempt = 0;
let intentionallyClosed = false;

function notify(connected: boolean) {
  connectionChangeFn?.(connected);
}

function scheduleReconnect() {
  if (intentionallyClosed || !useSession.getState().authenticated) return;
  reconnectAttempt += 1;
  const delay = Math.min(30_000, 1000 * 2 ** reconnectAttempt) + Math.random() * 1000;
  reconnectTimer = setTimeout(() => {
    void connectNow();
  }, delay);
}

async function connectNow(): Promise<void> {
  if (intentionallyClosed || !useSession.getState().authenticated) return;
  let ticket: string;
  try {
    const res = await apiClient.post<{ ticket: string }>("/ws/ticket");
    ticket = res.ticket;
  } catch {
    // сеть/401: 401 разлогинит через api-client; сеть — ретрай по таймеру
    scheduleReconnect();
    return;
  }

  if (socket) {
    // прежний сокет заменяется: его onclose увидит socket !== ws и не
    // запустит ещё один реконнект (иначе — экспоненциальный рост соединений)
    socket.close();
    socket = null;
  }
  const url = `${config.wsBase}?ticket=${encodeURIComponent(ticket)}`;
  const ws = new WebSocket(url);
  socket = ws;

  ws.onopen = () => {
    reconnectAttempt = 0;
    notify(true);
  };

  ws.onmessage = (raw) => {
    if (!dispatchFn) return;
    try {
      dispatchFn(JSON.parse(raw.data as string) as WsEnvelope);
    } catch {
      // некорректное событие игнорируем — не роняем приложение
    }
  };

  ws.onclose = () => {
    if (socket !== ws) return; // сокет заменён при реконнекте — не циклим
    notify(false);
    socket = null;
    // §3.2: истечение JWT в живом WS — норма, соединение не пере-валидируется;
    // реконнект (новый ticket) при живой сессии
    scheduleReconnect();
  };

  ws.onerror = () => {
    // onclose придёт после onerror — реконнект обрабатывает он
  };
}

export const wsClient: WsClient = {
  async connect() {
    intentionallyClosed = false;
    await connectNow();
  },
  disconnect() {
    intentionallyClosed = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = null;
    socket?.close();
    socket = null;
    notify(false);
  },
  sendTyping(chatId: string) {
    // client→server — только typing (§3.3, §9 концепции)
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "typing", data: { chat_id: chatId } }));
    }
  },
  onDispatch(fn) {
    dispatchFn = fn;
  },
  isConnected() {
    return socket?.readyState === WebSocket.OPEN;
  },
  onConnectionChange(fn) {
    connectionChangeFn = fn;
  },
};
