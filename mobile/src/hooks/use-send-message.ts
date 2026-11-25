/**
 * Отправка сообщения (§3.10): Idempotency-Key (uuid) + timezone (IANA устройства).
 * Статусы: sending → sent (2xx) | error (кнопка «повторить»).
 * Сообщение рисуется сразу (status=sending) — merge по client_ref (§6):
 * REST-ответ и WS message.new с одним client_ref — одна запись в ленте.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { randomUUID } from "../services/uuid";
import { messagesApi, type SendMessagePayload } from "../api/endpoints";
import { queryKeys } from "../api/query-keys";
import { useSession } from "../stores/session";
import type { LocalMessage, Message } from "../api/types";

/** Эффективный пояс отправителя (§6): клиент передаёт, сервер валидирует. */
function deviceTimezone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return undefined;
  }
}

/** Ключ идемпотентности — живёт в локальной записи до sent (ретрай тот же). */
const IDEMPOTENCY_KEY_FIELD = "__idempotency_key";

export type PendingLocalMessage = LocalMessage & { [IDEMPOTENCY_KEY_FIELD]?: string };

/** Вставка/замена сообщения в кэше ленты по id или client_ref. */
export function upsertMessageInCache(
  queryClient: ReturnType<typeof useQueryClient>,
  message: Message | LocalMessage,
) {
  const feedKey = queryKeys.messages.feed(message.chat_id);
  queryClient.setQueryData<{ pages: { messages: Message[] }[]; pageParams: unknown[] }>(
    feedKey,
    (old) => {
      if (!old) return old;
      const incoming = message as Message;
      const clientRef = (message as LocalMessage).client_ref ?? null;
      const localId = message.id.startsWith("local-") ? message.id : null;
      let replaced = false;
      const pages = old.pages.map((page) => {
        const idx = page.messages.findIndex(
          (m) =>
            m.id === incoming.id ||
            (clientRef && m.client_ref === clientRef) ||
            (localId && m.id === localId),
        );
        if (idx === -1) return page;
        replaced = true;
        const next = [...page.messages];
        // сохраняем локальный ключ идемпотентности (для ретрая) и статус
        next[idx] = { ...(next[idx] as PendingLocalMessage), ...incoming } as Message;
        return { ...page, messages: next };
      });
      if (replaced) return { ...old, pages };
      // новое сообщение → в конец последней страницы (ASC-порядок ленты)
      const pagesNext = [...old.pages];
      const lastIdx = pagesNext.length - 1;
      pagesNext[lastIdx] = {
        ...pagesNext[lastIdx],
        messages: [...pagesNext[lastIdx].messages, incoming],
      };
      return { ...old, pages: pagesNext };
    },
  );
}

export function useSendMessage(chatId: string) {
  const queryClient = useQueryClient();

  return useMutation<
    Message,
    Error,
    {
      text?: string;
      replyToId?: string;
      attachments?: SendMessagePayload["attachments"];
      /** Ключ идемпотентности — генерирует вызывающий (один для onMutate и mutationFn). */
      idempotencyKey: string;
    },
    { localMessage: PendingLocalMessage }
  >({
    mutationFn: ({ text, replyToId, attachments, idempotencyKey }) => {
      const payload: SendMessagePayload = {
        text,
        reply_to_id: replyToId,
        timezone: deviceTimezone(),
        ...(attachments && attachments.length > 0 ? { attachments } : {}),
      };
      return messagesApi.send(chatId, payload, idempotencyKey);
    },
    onMutate: ({ text, replyToId, attachments, idempotencyKey }) => {
      // client_ref = ключ идемпотентности: merge REST-ответа/WS с локальной
      // записью идёт по client_ref (id у сервера другой) — без него статус
      // навсегда остаётся "sending"
      const localMessage: PendingLocalMessage = {
        id: `local-${randomUUID()}`,
        chat_id: chatId,
        sender_id: useSession.getState().user?.id ?? null,
        type: "text",
        text: text ?? null,
        payload: null,
        client_ref: idempotencyKey,
        reply_to_id: replyToId ?? null,
        forward_from_message_id: null,
        forward_from_chat_id: null,
        forward_snapshot: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        timezone: null,
        edited_at: null,
        deleted_at: null,
        attachments: [],
        reactions: [],
        status: "sending",
        [IDEMPOTENCY_KEY_FIELD]: idempotencyKey,
      };
      upsertMessageInCache(queryClient, localMessage);
      return { localMessage };
    },
    onSuccess: (serverMessage) => {
      const withRef: LocalMessage = { ...serverMessage, status: "sent" } as LocalMessage;
      upsertMessageInCache(queryClient, withRef);
      void queryClient.invalidateQueries({ queryKey: queryKeys.chats.list() });
    },
    onError: (_error, _vars, context) => {
      if (!context) return;
      const failed = context.localMessage as PendingLocalMessage;
      upsertMessageInCache(queryClient, { ...failed, status: "error" });
    },
  });
}

/**
 * Повтор отправки «error»-сообщения (§3.4): тот же Idempotency-Key (§6 —
 * сервер вернёт созданное сообщение, дубля не будет; таймаут ≠ отсутствие).
 */
export function useRetryMessage(chatId: string) {
  const queryClient = useQueryClient();
  return useMutation<Message, Error, PendingLocalMessage>({
    mutationFn: (message) => {
      const key = message[IDEMPOTENCY_KEY_FIELD] ?? randomUUID();
      return messagesApi.send(
        chatId,
        { text: message.text ?? "", timezone: deviceTimezone() },
        key,
      );
    },
    onSuccess: (serverMessage) => {
      const withRef: LocalMessage = { ...serverMessage, status: "sent" } as LocalMessage;
      upsertMessageInCache(queryClient, withRef);
      void queryClient.invalidateQueries({ queryKey: queryKeys.chats.list() });
    },
    onError: (_error, message) => {
      upsertMessageInCache(queryClient, { ...message, status: "error" });
    },
  });
}
