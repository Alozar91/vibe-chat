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

  "profile.title": "Профиль",
  "profile.username": "Имя пользователя (изменить нельзя)",
  "profile.displayName": "Отображаемое имя",
  "profile.firstName": "Имя",
  "profile.lastName": "Фамилия",
  "profile.email": "Email",
  "profile.timeDisplay": "Режим отображения времени",
  "profile.timeDisplay.asSent": "Как отправлено",
  "profile.timeDisplay.fixed": "Фиксированный пояс",
  "profile.timeDisplay.utc": "UTC",
  "profile.timeDisplay.browser": "Мой часовой пояс",
  "profile.timezone": "Часовой пояс (IANA, например Europe/Moscow)",
  "profile.save": "Сохранить",
  "profile.saving": "Сохранение…",
  "profile.saved": "Сохранено",
  "profile.saveError": "Ошибка сохранения: {error}",
  "profile.logout": "Выйти",
  "profile.logoutConfirm": "Выйти из аккаунта?",
  "profile.personalNote": "Персональные данные хранятся в системе; Keycloak знает только логин и пароль (§5).",
  "profile.notifications": "Уведомления",
  "profile.notificationsOn": "Включены — настройка канала в системе",
  "profile.notificationsOff": "Отключены — включить в настройках системы",

  "forward.title": "Переслать сообщение",
  "forward.noChats": "Нет других чатов",
  "forward.send": "Переслать",
  "forward.sending": "Пересылка…",
  "forward.groupTag": "ГРУППА",
  "forward.done": "Переслано",

  "newChat.title": "Новый чат",
  "newChat.tabDirect": "Личный",
  "newChat.tabGroup": "Группа",
  "newChat.searchPlaceholder": "Поиск по логину или имени…",
  "newChat.groupTitlePlaceholder": "Название группы",
  "newChat.selected": "Выбрано: {count}",
  "newChat.create": "Создать",
  "newChat.creating": "Создание…",
  "newChat.empty": "Никого не найдено",
  "newChat.start": "Открыть чат",

  "info.title": "О чате",
  "info.members": "Участники ({count})",
  "info.role.owner": "владелец",
  "info.role.admin": "админ",
  "info.role.member": "участник",
  "info.rename": "Переименовать",
  "info.renamePlaceholder": "Новое название",
  "info.leave": "Покинуть группу",
  "info.leaveConfirm": "Покинуть группу?",
  "info.directHint": "Личный чат: участники и название — фиксированные (§12).",
  "info.you": "(вы)",

  "invites.title": "Инвайты (платформенный админ)",
  "invites.create": "Создать код",
  "invites.unlimited": "безлимит",
  "invites.uses": "использований: {count}/{max}",
  "invites.deactivate": "Деактивировать",
  "invites.deactivated": "деактивирован",
  "invites.codeOnce": "Код показывается один раз: {code}",
  "invites.empty": "Пока нет кодов",
  "invites.creating": "Создание…",

  "edit.title": "Редактирование сообщения",

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
