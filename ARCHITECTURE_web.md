# Вайб.Chat — Архитектура web-клиента (React)

Версия: 1.0. Статус: утверждена к реализации.
Документ развивает `ARCHITECTURE.md` (далее — **базовый документ**) в части web-клиента и фиксирует решения по реализации SPA на React. Нумерация разделов независима; ссылки на базовый документ — в виде «(базовый, §N)». Эндпоинты и структуры данных описаны в базовом документе (§8) и здесь не дублируются.

---

## 1. Обзор и границы

Web-клиент — SPA «Вайб.Chat» для одной организации:

- вход через **BFF** (Keycloak, cookie-сессия) — клиент никогда не работает с токенами;
- чаты: direct и групповые, участники, роли, invite-ссылки;
- сообщения: отправка, история, reply, пересылка, редактирование/удаление, markdown + mentions + `@all` (реакции и карточки — этап 2);
- файлы и медиа, аватары;
- realtime: WS-события, typing, presence, синхронизация при переподключении;
- уведомления: in-app, Web Push (VAPID), бейджи;
- поиск: сообщения, чаты, люди;
- админ-панель (`/admin`) — только `owner`/`admin` организации.

Вне границ документа: мобильные клиенты (Flutter), боты и webhook-доставка (этап 2), треды/каналы/звонки (этап 4). Дорожная карта web-части — раздел 21.

---

## 2. Зафиксированные решения

| Компонент | Выбор | Обоснование |
|---|---|---|
| Платформа | React 19 + TypeScript 5 (strict), Node 22 LTS | базовый документ, §2 («React + TypeScript (Vite)») |
| Сборка | Vite 7 | быстрый dev-сервер с прокси (same-origin для cookie), нативный ESM |
| Маршрутизация | React Router v7 (library mode) | вложенные layout'ы, guards, history API (nginx `try_files` уже настроен) |
| Серверное состояние | TanStack Query v5 | кэш, инвалидация из WS-событий, optimistic updates, infinite queries |
| Клиентское состояние | Zustand (минимально: WS-статус, typing, presence, composer) | всё остальное — серверный кэш; собственной «БД на клиенте» нет |
| API-типы и клиент | openapi-typescript + openapi-fetch, генерация из `/openapi.json` | базовый документ, §7 («TS-клиент генерируется из OpenAPI») |
| Realtime | нативный WebSocket + собственный менеджер (reconnect, heartbeat, sync) | один эндпоинт `/ws`, простой протокол (базовый, §9) |
| Стили | собственная CSS-система (`src/styles.css`, custom properties, светлая/тёмная тема) | ноль зависимостей сборки, полный контроль; Tailwind — при росте UI |
| UI-компоненты | собственный набор `components/ui` + headless-примитивы (Radix) для диалогов/поповеров | без тяжёлой дизайн-системы |
| Формы | react-hook-form + zod | профиль, админ-формы |
| Markdown | marked + DOMPurify (белый список тегов) | безопасный рендер недоверенного `body` |
| Виртуализация | @tanstack/react-virtual | лента сообщений, большие списки участников |
| Даты | dayjs | компактная, relative time |
| Тесты | Vitest + Testing Library (+ MSW), Playwright (e2e) | раздел 20 |
| Язык интерфейса | русский, строки в коде; i18n-слой — позже | не MVP |

Ключевые принципы:

1. **BFF-аутентификация**: HttpOnly cookie управляется бэкендом; на клиенте нет access/refresh-токенов (базовый, §5.3).
2. **Один источник истины — TanStack Query**: WS-события только обновляют кэш; отдельного клиентского стора сообщений нет.
3. **Сервер — источник истины по правам и лимитам**: клиент дублирует проверки (my_role, лимиты настроек) только для UX; 403/413/429 от сервера обрабатываются штатно.
4. **Same-origin везде**: prod — через nginx, dev — через vite-прокси; CORS не используется, cookie-сессии работают без настроек.
5. Дедуп событий — по `(chat_id, seq)` (базовый, §9).

---

## 3. Высокоуровневая структура

```text
┌──────────────────────────── SPA (web/) ────────────────────────────┐
│  pages (маршруты, guards)                    admin/*               │
│        │                                                           │
│  features: auth, chats, messages, media, profile,                  │
│            search, notifications, admin                            │
│        │                        │                                  │
│  хуки/мутации (Query)     realtime (ws-менеджер → диспетчер)       │
│        └───────────┬────────────┘                                  │
│              TanStack Query cache                                  │
│                    │                                               │
│  api/ (сгенерированные типы + fetch-обёртка: CSRF, ошибки, 401)    │
└────────────┬──────────────────────────────────┬────────────────────┘
             │ HTTPS: cookie + X-CSRF-Token     │ WSS: cookie
             ▼                                  ▼
      nginx ──► api /v1/…                 nginx ──► api /ws
```

---

## 4. Структура проекта

```text
web/
  package.json
  vite.config.ts            # прокси /v1 и /ws на api:8000; env
  index.html
  Dockerfile                # multi-stage: node build → dist
  public/
    service-worker.js       # Web Push (раздел 13)
  src/
    main.tsx
    app/                    # App, провайдеры (QueryClient, Router), layout, guards
    api/                    # api.d.ts (генерация), client.ts (fetch + CSRF + ошибки)
    realtime/               # ws.ts (менеджер), events.ts (диспетчер), store.ts
    features/
      auth/                 # guard, редирект на вход, активные сессии
      chats/                # список, создание, участники, настройки чата, invites
      messages/             # лента, composer, действия, forward, mentions
      media/                # upload pipeline, превью, аватар
      profile/              # /me, notification_settings
      search/
      notifications/        # push-подписка, тосты, бейджи
      admin/                # users, sessions, stats, audit, bots
    components/ui/          # Button, Input, Modal, Popover, Avatar, Toast, …
    lib/                    # markdown.ts, mentions.ts, time.ts, files.ts
    types/                  # ApiError и общие типы
```

Правило зависимостей: фичи не импортируют друг друга напрямую — только через публичные хуки/компоненты фичи либо общий уровень (`api`, `lib`, `components`).

---

## 5. Аутентификация и сессии (BFF)

Основной способ входа — **встроенная форма в SPA** (`/login`), без ухода с сайта:

```text
1. 401 от любого API → редирект на /login?next=<текущий путь SPA>
2. Пользователь вводит логин/пароль → POST /v1/auth/direct-login {username, password}
3. Бэкенд обменивает учётные данные на токены через Keycloak (password grant,
   client_secret только на сервере), проверяет id_token, JIT-создаёт/обновляет
   пользователя и создаёт Valkey-сессию
4. Ответ: cookie session (HttpOnly) + csrf + JSON профиля → SPA кладёт его в кэш
   ["me"] и переходит на next; токены Keycloak в браузер не попадают
5. Ограничение: 10 попыток/мин/IP (429 с Retry-After)
```

Fallback — кнопка «Войти через страницу Keycloak» (`GET /v1/auth/login?origin=…` → стандартный authorization code flow): нужен при включённой MFA (TOTP) или обязательной смене пароля (required action UPDATE_PASSWORD) — direct grant эти сценарии не поддерживает, Keycloak возвращает 400/401 с описанием, которое форма показывает как ошибку.

Защита от цикла: 401, полученный на самой странице `/login` (запрос `me` без сессии), не вызывает редирект — глобальный обработчик пропускает пути `/login*`, а `sanitizeNext` схлопывает вложенные `next=/login…` в `/`.

Правила:

- Guard маршрутов: пока `GET /v1/me` в загрузке — full-screen loader; 401 → редирект на `/login?next=…` (встроенная форма). Страницы логина в Keycloak в SPA нет — вход на `/login` или через fallback-кнопку. `?origin=` fallback-кнопки проверяется бэкендом по allowlist — клиент ничему не доверяет проверку.
- Guard маршрутов: пока `GET /v1/me` в загрузке — full-screen loader; 401 → редирект на вход; успех → доступ. Запрос `/v1/me` не ретраится.
- Роли: `role` из `/v1/me` → доступ к `/admin` (`owner`|`admin`). Обновление роли — refetch `/v1/me` по рефокусу окна и по 403-ответам.
- Выход: `POST /v1/auth/logout` (с CSRF) → очистка кэша Query → редирект на вход. `POST /v1/auth/logout-all` — на странице «Активные сессии».
- «Активные сессии»: `GET /v1/auth/sessions`, отзыв `DELETE /v1/auth/sessions/{session_id}` (текущая помечена `current: true`).
- Смена пароля — только через консоль Keycloak (`/realms/messenger/account`), ссылка в профиле. В SPA не реализуется.
- Cookie-сессия скользящая (TTL 12 ч, продлевает бэкенд) — клиент ничего не продлевает.

Dev-режим (`vite.config.ts`):

```ts
server: {
  proxy: {
    "/v1": { target: "http://localhost:8000" },
    "/ws": { target: "ws://localhost:8000", ws: true },
  },
}
```

Same-origin ⇒ cookie-сессии и WS работают в dev без CORS-настроек.

---

## 6. HTTP-клиент

- Типы генерируются из OpenAPI: `npm run api:types` (openapi-typescript, источник `http://localhost:8000/openapi.json`, результат коммитится в `src/api/api.d.ts`). Запросы — openapi-fetch.
- Обёртка `client.ts`:
  - baseURL пустой (same-origin);
  - на POST/PATCH/PUT/DELETE — `X-CSRF-Token` из csrf-cookie;
  - не-2xx → `ApiError { status, code, message, details, retryAfter? }` по единому формату `{ "error": { "code", "message", "details" } }` (базовый, §8.1);
  - `401 unauthorized` → глобальный обработчик: сброс кэша, редирект на `/v1/auth/login?origin=…`;
  - `429 rate_limited` → `retryAfter` из `Retry-After`: composer/действие блокируется с таймером;
  - `Idempotency-Key` добавляет слой outbox (раздел 9), не каждая мутация.
- Пагинация: сообщения — infinite query по `before_seq` (+ `after_seq` для resync), списки — `offset` + `next_offset`/`has_more`.

---

## 7. Серверное состояние (TanStack Query)

Ключи кэша:

```text
["me"]                                ["settings"]
["chats", {limit}]                    ["chat", chatId]
["chat", chatId, "messages"]          ["chat", chatId, "members", …]
["chat", chatId, "invites"]           ["search", type, params]
["admin", …]
```

- `staleTime`: chats 10 c, me/settings 5 мин, members 30 c. Рефокус окна → refetch `me` и `chats`.
- Инвалидация — только из WS-событий и результатов мутаций. Поллинга нет, кроме fallback-режима без WS (раздел 18).
- Optimistic updates: отправка/редактирование/удаление сообщения, отметка прочтения, настройки чата (`PATCH members/me`).
- Лимиты кэша: ≤ ~1000 сообщений на чат (обрезка старейших страниц), 20 страниц списка чатов; `gcTime` неактивных чатов — 5 мин.
- `GET /v1/settings` кэшируется и используется для клиентской валидации: `message_max_length`, `max_file_size_mb`, `max_attachments`, `all_mention_threshold` (базовый, §8.2).

---

## 8. Realtime (WebSocket)

Подключение: `wss(s)://<host>/ws` (URL выводится из `location`: `(https:|wss:)`); аутентификация — cookie автоматически; heartbeat 30 c (базовый, §9).

Менеджер (`src/realtime/ws.ts`) — singleton:

- состояние `connecting | online | offline` в Zustand → индикатор в шапке;
- heartbeat: ping каждые 30 c; нет ответа/ошибка → закрытие и переподключение;
- reconnect: экспоненциальный backoff 1→30 c с jitter; при повторных неудачах раз в ~5 попыток проверять `/v1/me` (сессия истекла → редирект на вход, а не бесконечный ретрай);
- `onopen`: отправить `sync.request` (ниже); typing-состояние восстанавливается естественно;
- при `offline` исходящие typing/heartbeat не копятся (droppable), `sync.request` — один активный.

Диспетчер событий (`events.ts`), событие → действие:

| Событие | Действие клиента |
|---|---|
| `message.new` | дедуп по `(chat_id, seq)`; append в `["chat", id, "messages"]`; обновить chats (`last_message_*`, `unread`+1 если чат не активен или вкладка в фоне); тост/звук по настройкам; если чат активен и вкладка в фокусе — `POST /read` |
| `message.updated` | заменить сообщение в кэше |
| `message.deleted` | tombstone: тело → «Сообщение удалено», вложения скрыть |
| `chat.updated` | обновить/вставить чат в список |
| `chat.member.joined` / `chat.member.left` | invalidate `["chat", id, "members"]`, `members_count` |
| `chat.read` | маркер «прочитано» (last_read_seq участника) в кэше members |
| `typing.start` / `typing.stop` | набор печатающих чата, TTL 5 c («Иван печатает…») |
| `presence.update` | presence-набор (online/last_seen), TTL 60 c |
| `notification.badge` | суммарный бейдж (`navigator.setAppBadge` / `clearAppBadge`, fallback — `document.title`) |

Синхронизация при (пере)подключении (базовый, §9):

```json
{ "type": "sync.request", "chats": [{ "chat_id": "uuid", "last_seq": 1200 }] }
```

- `last_seq` — последний загруженный seq из кэша сообщений + localStorage-снапшот `{chatId: lastSeq}` (обновляется при каждом message.new и read) — resync работает и после перезагрузки страницы;
- пропущенное приходит как `message.new` → тот же путь дедупа;
- если в незагруженной части истории образовался «разрыв» seq — пометка «есть новые сообщения», дозагрузка через REST `after_seq` при прокрутке/открытии.

typing (клиент → сервер): при вводе `typing.start` не чаще раза в 3 c; `typing.stop` — через 3 c тишины или при отправке.

---

## 9. Отправка сообщений (outbox клиента)

Поток (базовый, §8.4):

```text
1. submit → outbox.push({ idempotencyKey: uuid, chatId, body,
                          replyToSeq, attachments(file_id), forward })
2. Optimistic: temp-сообщение в ленте (status: sending, дедуп-ключ = idempotencyKey)
3. POST /v1/chats/{id}/messages с заголовком Idempotency-Key
4. 201/200 → заменить temp на серверное сообщение по (chat_id, seq)
5. Сеть/5xx → ретрай с backoff, ТОТ ЖЕ ключ (сервер вернёт 200 + исходное — без дубля)
6. 4xx → статус failed + «Повторить»/«Удалить» (новый ключ при «Повторить» после правки)
7. WS message.new со своим seq до ответа POST — не создаёт дубля: дедуп после подтверждения
```

- Очередь персистится в localStorage (по чату), восстанавливается при перезагрузке; после подтверждения удаляется.
- Вложения ставятся в очередь только уже загруженными `file_id` — upload идёт до постановки в очередь (раздел 12).
- Порядок: в рамках чата отправка последовательная; между чатами — параллельная.
- Редактирование/удаление — `PATCH`/`DELETE` с optimistic-обновлением кэша; окно редактирования не ограничено (конфиг сервера).
- Пересылка: модалка мультивыбора чатов → `POST /messages { "forward": [{chat_id, seq}, …] }`; у получателя рендерится блок `data.forwarded_from` (базовый, §6.3).

---

## 10. Экраны и маршруты

| Маршрут | Экран | Доступ |
|---|---|---|
| (вне защищённой зоны) `/login` | встроенная форма входа: `POST /v1/auth/direct-login` → куки-сессия → переход на `?next=`; fallback-кнопка на Keycloak-редирект | все |
| (вне SPA) `/v1/auth/login` | редирект на Keycloak (fallback для MFA/смены пароля) | все |
| `/` | редирект: последний чат (localStorage) или первый из списка; пустое состояние «Нет чатов» + приглашение создать | авторизованный |
| `/chat/:chatId` | лента + composer + панель информации чата (участники, настройки, invites) | участник |
| `/me` | профиль `PATCH /v1/me`, `notification_settings`, аватар, «Активные сессии», logout | авторизованный |
| `/settings` | локальные настройки: тема, звук (не серверные) | авторизованный |
| `/join/:code` | приглашение: `POST /v1/invites/join/{code}` → редирект в чат; ошибки 404/410/429 — понятными текстами | авторизованный |
| `/admin` | dashboard: `GET /v1/admin/stats` | owner/admin |
| `/admin/users`, `/admin/users/:id` | список/карточка, создание, CSV-импорт, сброс пароля, disable/enable | owner/admin |
| `/admin/sessions` | сессии пользователей (`?user_id=`), отзыв | owner/admin |
| `/admin/audit` | журнал аудита | owner/admin |
| `/admin/bots` | боты организации, токены, disable | owner/admin |

Layout: двухпанельный (список чатов слева, контент справа); < 768 px — однопанельный со стек-навигацией. Создание чата: «Direct» — поиск пользователя (`GET /v1/users/search`) → `POST /v1/chats {type:"direct", user_id}`; «Группа» — title + мультивыбор участников. Приглашения-ссылки — в панели информации чата (`POST /v1/chats/{id}/invites`, копирование `url`, отзыв).

Для `source=ldap` поля профиля read-only (редактируются синком, базовый §5.6); `avatar_file_id` и `notification_settings` редактируемы; любые 403 от сервера обрабатываются без поломки формы.

---

## 11. Лента сообщений: UI-механики

- Виртуализация (@tanstack/react-virtual); группировка подряд идущих сообщений одного автора (≤ 5 мин); разделители дат; автоскролл к низу; кнопка «Вниз» + счётчик новых.
- История: infinite вверх по `before_seq` (страница 50); при входе в чат — разделитель непрочитанных по `last_read_seq`; resync вниз по `after_seq`.
- Прочитано: активный чат + фокус вкладки + последнее сообщение видно → `POST /v1/chats/{id}/read {last_read_seq}` (debounce 500 мс) → `unread: 0` в кэше.
- Пузырь: автор/время, markdown, подсветка mentions и `@all`, превью вложений, reply-цитата, forwarded-блок, `edited_at`, статус отправки (⏳/✓/failed), реакции — этап 2.
- Действия — из матрицы прав (базовый, §5.7): свои сообщения — edit/delete; чужие delete — при `my_role` owner/admin чата. Кнопки рендерим по `my_role` (UX); сервер — источник истины, 403 обрабатываем тихо.
- Контекстное меню: Ответить, Копировать, Переслать, Редактировать, Удалить (с подтверждением).
- Composer: авторазмер, Enter — отправить, Shift+Enter — перенос; счётчик `message_max_length`; вставка изображений из буфера и drag&drop файлов; reply/forward-превью-бары; упоминания: триггер `@` → выпадающий поиск (`users/search`), вставка как `@username`; `@all` предлагается при `members_count <= all_mention_threshold`; блокировка на `Retry-After` при 429.

---

## 12. Файлы и медиа

Поток загрузки (базовый, §11):

```text
1. Клиентская валидация: размер ≤ max_file_size_mb, MIME в whitelist,
   ≤ max_attachments на сообщение (из GET /v1/settings)
2. POST /v1/media/upload-intents → { file_id, upload_url, headers }
3. PUT upload_url — через XHR: нужен прогресс загрузки (fetch не умеет upload progress)
4. POST /v1/media/upload-complete → status ready, av_status pending
5. file_id в attachments при отправке сообщения
```

- Карточки прогресса в composer; отмена — abort XHR (осиротевший объект в S3 чистит retention).
- `av_status=infected` → вложение скрывается, плашка «Файл заблокирован»; статус подхватывается при перезагрузке ленты (отдельного WS-события в MVP нет — открытый вопрос №3).
- Скачивание/превью: `GET /v1/media/{file_id}/url` → presigned GET 5 мин; полученный url кэшируется в памяти сообщения ≤ 4 мин; изображения/видео — `thumbnail_url`; клик — лайтбокс с каруселью вложений сообщения.
- Аватар: upload → `PATCH /v1/me { avatar_file_id }`.

---

## 13. Уведомления

- In-app: тост при `message.new` вне активного чата (клик → чат); звук (настраиваемый); бейдж вкладки (`document.title`) + `navigator.setAppBadge` из `notification.badge`/unread.
- Web Push (VAPID, базовый §2, §10):
  - Service Worker (`public/service-worker.js`): событие `push` → `showNotification`; `notificationclick` → фокус окна + `postMessage` → навигация в чат;
  - подписка: по кнопке в `/me` (или при первом входе) → `Notification.requestPermission()` → `pushManager.subscribe(VAPID)` → `POST /v1/devices { "platform": "web", "webpush_subscription": { endpoint, keys } }`;
  - отказ в разрешении не блокирует работу; при logout — `DELETE /v1/devices/{device_id}` (device сопоставляется по `endpoint`);
  - push требует TLS (кроме localhost); VAPID-ключ — `VITE_VAPID_PUBLIC_KEY`.
- FCM/APNs-каналы — не для web; web-устройство регистрируется только с webpush_subscription.

---

## 14. Поиск

- Глобальный поиск (шапка / Cmd+K): debounce 300 мс → `GET /v1/search`; табы «Сообщения / Чаты / Люди»; фильтры сообщений: чат, автор, диапазон дат.
- Клик по найденному сообщению → открыть чат и загрузить страницу вокруг seq (`before_seq`/`after_seq`), подсветка.
- Права не проверяются клиентом — сервер фильтрует по членству (базовый, §13).

---

## 15. Админ-панель

- Guard: `role ∈ {owner, admin}`; иначе заглушка 404 (не раскрываем существование раздела).
- Пользователи: таблица (пагинация 50) + поиск; создание `POST /v1/admin/users` — при `send_email=false` `temporary_password` показывается **один раз** (модалка «скопируйте сейчас»); CSV-импорт (multipart, отчёт `created`/`failed` построчно); сброс пароля (тот же показ одноразового пароля); disable/enable с подтверждением (активные сессии закроются ≤ 30 c, базовый §5.5).
- Сессии: `GET /v1/admin/sessions?user_id=`, `DELETE /v1/admin/sessions/{id}`; свои — в `/me/sessions`.
- Stats: карточки `dau`, `messages_per_day`, `users_total`, `chats_total`, `storage_bytes` (человекочитаемый формат).
- Audit: таблица `GET /v1/admin/audit` с пагинацией, фильтр по `action`.
- Боты: список `GET /v1/admin/bots`, disable; создание/токены — через `/v1/bots*` (показ токена один раз).
- Маскирование email/телефона для role=member — на сервере; клиент отображает как есть.

---

## 16. Безопасность на клиенте

- **XSS**: `body` сообщений — недоверенный ввод; рендер markdown только через sanitize (DOMPurify, белый список: `b, strong, em, i, code, pre, a, ul, ol, li, blockquote, p, br`); ссылки — https-only, `target="_blank"` + `rel="noopener noreferrer"`; `dangerouslySetInnerHTML` запрещён вне единственного санитайзера.
- **CSRF**: `X-CSRF-Token` на всех мутациях; токен перечитывается из cookie при повторном входе (бэкенд перезаписывает csrf-cookie).
- **Данные на клиенте**: в localStorage только UI-состояние (тема, последний чат, снапшот last_seq, outbox-очередь) — никаких токенов и ПДн; presigned URL хранятся в памяти кэша Query.
- **CSP** (рекомендация для nginx): `default-src 'self'; connect-src 'self' wss:; img-src 'self' https: data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'`.
- Зависимости: `npm audit` + автоматические обновления (renovate/dependabot) в CI; lockfile в репозитории.

---

## 17. Производительность

- Code splitting по маршрутам (React.lazy): `/admin`, поиск, лайтбокс — отдельные чанки.
- Лента: виртуализация; изображения — `thumbnail_url` + lazy; heavy-компоненты (лайтбокс, forward-модалка) — lazy.
- Троттлинг: typing 1 раз/3 c; read — debounce 500 мс; presence — TTL-набор, без перерисовок по каждому событию.
- Кэш: лимиты раздела 7; обрезка старых страниц сообщений.
- Бюджет начального чанка ≤ 250 КБ gzip (без admin/search); контроль в CI (size-limit — опционально).

---

## 18. Отказоустойчивость (клиент)

| Ситуация | Поведение клиента |
|---|---|
| WS недоступен / разрыв | индикатор «переподключение»; reconnect с backoff; после reconnect — `sync.request`; отправка продолжается через REST |
| WS нет дольше 60 c | fallback-поллинг: refetch chats каждые 15 c, активного чата — каждые 10 c, до восстановления WS |
| Ответ 503 degraded | баннер «Сервис ограниченно доступен»; отправка продолжается (пишет Postgres, базовый §16) |
| 401 | сброс кэша → редирект на вход (в т.ч. после сбоя Valkey с потерей сессий) |
| 429 | действие блокируется на `Retry-After`, показ причины |
| Офлайн (`navigator.onLine`) | баннер; outbox копится, отправка при восстановлении |
| Ошибка загрузки файла | ретрай с нового `upload-intents`; загрузка с начала (presigned PUT одночастный) |
| Медленный resync | в чате — плейсхолдер «Синхронизация…» на месте разрыва |

---

## 19. Конфигурация и сборка

Env (Vite, подставляются при сборке):

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `VITE_VAPID_PUBLIC_KEY` | — | ключ для `pushManager.subscribe` |
| `VITE_KEYCLOAK_URL` | `http://localhost:8081` | ссылка на консоль аккаунта Keycloak (смена пароля) |
| `API_PROXY_TARGET` (dev, process.env) | `http://localhost:8001` | цель dev-прокси `/v1` и `/ws` (порт api в compose) |

Базовый URL API — всегда same-origin (`/v1`), WS — `(wss:|ws:)//location.host/ws`; отдельные `VITE_API_BASE`/`VITE_WS_URL` не используются.

Presigned-URL (upload/download) подписываются на `S3_PUBLIC_URL` (deploy-по-умолчанию `http://localhost:9000`, порт MinIO проброшен), а не на внутренний `S3_ENDPOINT_URL` (`http://minio:9000`) — иначе браузер получит недоступный из его сети host.

- Скрипты: `dev / build / preview / test / lint / typecheck / api:types`.
- Dockerfile (multi-stage): `node:22-alpine` → `npm ci` → `build` → артефакт `dist`.
- **Контракт деплоя**: статика должна оказаться в `/usr/share/nginx/html/web` контейнера nginx (`deploy/nginx/nginx.conf`: `location / → try_files … /index.html` — уже настроено; `/v1` и `/ws` проксируются тем же nginx — same-origin). Варианты: (а) prod — образ nginx собирается с копированием `dist`; (б) dev-compose — volume-монтирование `../web/dist:ro`.
- Роутинг — history API; любой путь без расширения → `index.html` (покрыто `try_files`).
- CI: eslint + prettier, `tsc --noEmit`, vitest, build.

---

## 20. Тестирование

- **Unit (Vitest)**: санитайзер markdown, вставка/парсинг mentions, форматирование времени, валидация файлов по лимитам, ws-менеджер (backoff, sync — на мок-сокете), outbox (ретраи, тот же Idempotency-Key).
- **Component (RTL + MSW)**: composer (отправка, ошибки, 429 с таймером), лента (пагинация, дедуп по `(chat_id, seq)`), админ-формы.
- **E2E (Playwright, стек `docker compose up -d postgres valkey keycloak minio api`)**:
  - вход через тестовый realm → `/v1/me` → список чатов;
  - два контекста браузера: A отправляет → B получает < 2 c (WS), непрочитанные, typing, маркеры прочтения;
  - ретрай POST с тем же `Idempotency-Key` → без дубля;
  - upload → превью → сообщение с вложением; join по invite-ссылке (успех и 410);
  - admin: создание пользователя, disable → у B 401 на следующем запросе (≤ 30 c).
- Дым в CI — без Keycloak (MSW-моки); полный e2e — nightly.

---

## 21. Этапы реализации (web)

| Этап | Содержимое | Результат |
|---|---|---|
| **W0. Каркас** | Vite+TS+Tailwind, роутер, `api:types`, `client.ts` (CSRF/ошибки/401), layout, dev-прокси, CI | пустое SPA за nginx |
| **W1. Вход и профиль** | guard по `/v1/me`, BFF-редирект, `/me`, `notification_settings`, сессии, logout | вход/выход работают |
| **W2. Чаты и сообщения** | список чатов, лента (REST, пагинация), composer (идемпотентность, reply, edit/delete, forward, mentions), read | полный обмен без realtime |
| **W3. Realtime** | ws-менеджер, диспетчер событий, `sync.request`, typing, presence, индикатор | доставка < 2 c |
| **W4. Файлы** | upload pipeline, прогресс, превью, аватар | вложения |
| **W5. Уведомления** | тосты, бейджи, Web Push + service worker | push на web |
| **W6. Поиск** | глобальный поиск, переход к сообщению | |
| **W7. Админка** | users / sessions / stats / audit / bots | |
| **W8. Полировка** | офлайн-поведение, e2e Playwright, bundle-бюджет, тёмная тема, a11y-проход | релиз MVP |

Этап 2 базовой дорожной карты (реакции, карточки, закрепление) расширяет composer и пузырь сообщения, не меняя модель данных клиента.

---

## 22. Открытые вопросы (не блокируют реализацию)

1. `Message.attachments` содержит готовые `url`/`thumbnail_url` (базовый, §8.2) — в текущем бэкенде это относительные пути `/v1/media/{id}/url`, клиент резолвит presigned-URL по требованию с кэшем 4 мин; отдельный запрос на каждое вложение остаётся точкой роста.
2. Формат payload Web Push (объём, приватность текста) — текущий: `{title, body, sender_id}` без `chat_id`, клик по уведомлению открывает приложение без навигации в чат; согласовать при доработке worker'а (базовый, §10).
3. `av_status=infected`: WS-событие о блокировке файла или только tombstone при перезагрузке ленты — уточнить при доработке.
4. Точный контракт ответа на `sync.request` — реализован как поток `message.new` (без attachments/mentions) с лимитом 200 на чат; зафиксировано с бэкендом.
5. Минимальная поддержка мобильных браузеров (iOS Safari ≥ 16, Android Chrome ≥ 110) и поведение двухпанельного layout — проверить на реальных устройствах.
6. `GET /v1/settings` в бэкенде пока не реализован — клиент использует константы (4096 символов, 10 вложений, 100 МБ, порог @all = 100); перейти на серверные лимиты при появлении эндпоинта.
7. ~~Снятие mute в чате~~ — реализовано: `PATCH /members/me` принимает `muted_until=null` (роутер больше не отбрасывает `exclude_none`, сервис применяет только не-None значения `notifications`).
