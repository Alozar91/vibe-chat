import { queryClient } from "../../app/query";
import { messagesApi, type MessageSendPayload } from "../../api/endpoints";
import type { Attachment, Message } from "../../api/types";
import { isApiError } from "../../api/client";
import { appendMessages, createTempMessage, removeTempMessage, replaceTempMessage, setTempStatus } from "./queries";

interface OutboxItem {
  key: string;
  chatId: string;
  payload: MessageSendPayload;
}

const STORAGE_KEY = "vibe.outbox.v1";
const MAX_RETRY_DELAY_MS = 30000;

class Outbox {
  private queue: OutboxItem[] = [];
  private pumpingChats = new Set<string>();
  private attempts = new Map<string, number>();
  private timers = new Map<string, number>();
  private failedKeys = new Set<string>();

  constructor() {
    this.restore();
  }

  private restore() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as OutboxItem[];
      if (Array.isArray(parsed)) this.queue = parsed.filter((item) => item && item.key && item.chatId);
    } catch {
      this.queue = [];
    }
  }

  private persist() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.queue));
    } catch {
      return;
    }
  }

  enqueue(chatId: string, senderId: string, payload: MessageSendPayload, attachments: Attachment[]): Message {
    const key = this.newKey();
    const temp = createTempMessage(chatId, senderId, key, payload, attachments);
    this.queue.push({ key, chatId, payload });
    this.persist();
    appendMessages(queryClient, chatId, [temp]);
    void this.pump(chatId);
    return temp;
  }

  private newKey(): string {
    return crypto.randomUUID().replace(/-/g, "");
  }

  private nextFor(chatId: string): OutboxItem | undefined {
    return this.queue.find((item) => item.chatId === chatId && !this.failedKeys.has(item.key));
  }

  private remove(key: string) {
    this.queue = this.queue.filter((item) => item.key !== key);
    this.attempts.delete(key);
    this.failedKeys.delete(key);
    this.persist();
  }

  async pump(chatId: string) {
    if (this.pumpingChats.has(chatId)) return;
    this.pumpingChats.add(chatId);
    try {
      let item = this.nextFor(chatId);
      while (item) {
        const current = item as OutboxItem;
        if (this.timers.has(current.key)) break;
        try {
          const message = await messagesApi.send(chatId, current.payload, current.key);
          this.remove(current.key);
          replaceTempMessage(queryClient, chatId, current.key, message);
          item = this.nextFor(chatId);
        } catch (error) {
          if (isApiError(error) && error.status >= 400 && error.status < 500 && error.status !== 429) {
            this.failedKeys.add(current.key);
            setTempStatus(queryClient, chatId, current.key, "failed", error.message);
            item = this.nextFor(chatId);
            continue;
          }
          this.scheduleRetry(chatId, current.key);
          break;
        }
      }
    } finally {
      this.pumpingChats.delete(chatId);
    }
  }

  private scheduleRetry(chatId: string, key: string) {
    const attempt = (this.attempts.get(key) || 0) + 1;
    this.attempts.set(key, attempt);
    const delay = Math.min(MAX_RETRY_DELAY_MS, 1000 * 2 ** (attempt - 1));
    const existing = this.timers.get(key);
    if (existing) window.clearTimeout(existing);
    const timer = window.setTimeout(() => {
      this.timers.delete(key);
      void this.pump(chatId);
    }, delay);
    this.timers.set(key, timer);
  }

  retry(chatId: string, key: string) {
    const item = this.queue.find((i) => i.key === key);
    if (!item) return;
    this.attempts.delete(key);
    this.failedKeys.delete(key);
    setTempStatus(queryClient, chatId, key, "sending");
    void this.pump(chatId);
  }

  cancel(chatId: string, key: string) {
    this.remove(key);
    removeTempMessage(queryClient, chatId, key);
  }

  retryAllFailed(chatId: string) {
    const keys = this.queue.filter((item) => item.chatId === chatId && this.failedKeys.has(item.key)).map((item) => item.key);
    for (const key of keys) this.retry(chatId, key);
  }
}

export const outbox = new Outbox();

export function sendMessageWithOutbox(
  chatId: string,
  senderId: string,
  payload: MessageSendPayload,
  attachments: Attachment[],
): Message {
  return outbox.enqueue(chatId, senderId, payload, attachments);
}
