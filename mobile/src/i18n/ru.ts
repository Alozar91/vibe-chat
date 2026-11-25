/**
 * i18n (§3.10): хардкод строк в компонентах запрещён — только словарь.
 * MVP: один язык (ru); ключи — контракт для будущих локалей.
 */

export const ru = {
  "common.retry": "Повторить",
  "common.cancel": "Отмена",
  "common.send": "Отправить",
  "common.delete": "Удалить",
  "common.edit": "Изменить",
  "common.reply": "Ответить",
  "common.forward": "Переслать",
  "common.loading": "Загрузка…",
  "common.empty": "Пусто",
  "common.networkError": "Нет соединения",
  "common.unknownError": "Ошибка. Попробуйте ещё раз",

  "chats.title": "Чаты",
  "chats.empty": "Нет чатов. Найдите пользователя, чтобы начать общение.",
  "chats.unread": "новых",
  "chats.offlineBanner": "Нет соединения — сообщения отправятся позже",
  "chats.deletedChat": "Чат удалён",
  "chats.profile": "Профиль",
  "chats.groupSubtitle": "Групповой чат",
  "chats.directSubtitle": "Личный чат",

  "chat.inputPlaceholder": "Сообщение…",
  "chat.typing": "печатает…",
  "chat.typingMany": "печатают…",
  "chat.statusSending": "Отправка…",
  "chat.statusError": "Не отправлено",
  "chat.deletedMessage": "Сообщение удалено",
  "chat.attachPhoto": "Фото",
  "chat.attachFile": "Файл",
  "chat.attachProgress": "Загрузка {percent}%",
  "chat.editedMark": "изменено",
  "chat.replyingTo": "Ответ на: {text}",
  "chat.historyLoading": "Загрузка истории…",

  "viewer.title": "Просмотр",
} as const;

export type I18nKey = keyof typeof ru;

const dict: Record<I18nKey, string> = ru;

export function t(key: I18nKey, vars?: Record<string, string | number>): string {
  let str: string = dict[key];
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      str = str.replace(`{${k}}`, String(v));
    }
  }
  return str;
}
