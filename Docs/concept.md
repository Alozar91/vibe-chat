# Vibe Chat — общая концепция

> Статус: бэкенд MVP реализован (этапы 1–8, 2026-11-11); фронтенд — следующий этап.
> Документ — источник правды по продукту и архитектуре.
> Решения, помеченные «⚠️ не выбрано», требуют решения при старте соответствующего этапа.

## 1. Обзор

**Vibe Chat** — корпоративный мессенджер (self-hosted): личные и групповые чаты, боты с собственным API, обмен файлами и фото, в перспективе — mini-apps, звонки и мобильные приложения.

**Масштаб MVP:** до ~1000 пользователей, один инстанс бэкенда. Архитектура не должна блокировать горизонтальное масштабирование, но оптимизация под него — не цель MVP.

## 2. Стек

| Слой | Технология |
|---|---|
| Backend | Python 3.12+, FastAPI, SQLAlchemy + Alembic, Pydantic v2 / pydantic-settings |
| Frontend | React + TypeScript, Vite. Только веб-версия; мобильные — перспектива |
| СУБД | PostgreSQL (основное хранилище всего: пользователи, чаты, сообщения, файлы-метаданные) |
| Кэш / Pub/Sub | **Valkey** (не Redis) |
| Объектное хранилище | **Silo** (S3-совместимый, форк MinIO от Pigsty; не MinIO) |
| Авторизация | Keycloak (OIDC/JWT) |
| Realtime | WebSocket |
| Деплой | Docker Compose |
| Frontend: UI-кит | Tailwind CSS + shadcn/ui |
| Frontend: data layer | TanStack Query (кэш REST) + Zustand (WS-состояние: typing, presence, оптимистичные апдейты) |
| CI | Пока нет; локальные проверки: ruff/mypy/pytest, oxlint/tsc/vitest. Решить при появлении второй площадки |
| Реакции | Эмодзи-реакции на сообщения (👍❤️😄...) — в MVP (решено 2026-11-11); схема в §6, API в §12 |
| Звонки | **LiveKit** (self-hosted SFU, Apache 2.0) + coturn (TURN) — этапы A/B/C (§17): сигналинг звонка — наш WS (§9), медиа-сигналинг — LiveKit |

## 3. Структура монорепо

```
backend/
  app/
    api/v1/        # REST-роуты (версионируем с первого дня — ботам нужна стабильность)
    ws/            # WebSocket-эндпоинт и обработчики событий
    models/        # SQLAlchemy-модели
    schemas/       # Pydantic-схемы (API-контракты)
    services/      # бизнес-логика, без HTTP
    core/          # конфиг (pydantic-settings), security, зависимости
  alembic/
  tests/
frontend/
  src/
Docs/
deploy/
  docker-compose.yml
  .env.example
  keycloak/        # realm-export.json — конфигурация realm'а в виде кода
```

## 4. Архитектура

```
┌──────────┐   REST + WS    ┌─────────────┐   SQL    ┌────────────┐
│  React   │◄──────────────►│  FastAPI    │◄────────►│ PostgreSQL │
│  (web)   │                │  (1..N)     │          └────────────┘
└────┬─────┘                │             │   кэш/presence/fanout
     │                      │             │◄────────►┌────────────┐
     │ OIDC (Auth Code+PKCE)│             │          │   Valkey   │
     ▼                      │             │          └────────────┘
┌──────────┐                │             │   presigned PUT/GET
│ Keycloak │                │             │◄────────►┌────────────┐
└──────────┘                └─────┬───────┘          │    Silo    │
                                  │ Bot API (long polling)      └────────────┘
                            ┌─────▼───────┐
                            │    Боты     │ (внутренние сервисы)
                            └─────────────┘
```

Принципы:
- Бэкенд **не выдаёт** свои токены — только валидирует JWT Keycloak'а. Единственное исключение — скоупед opaque-токены mini-apps (§11).
- Файлы не проксируются через бэкенд: presigned URL напрямую в Silo.
- Любое realtime-событие для WS-клиентов публикуется через Valkey Pub/Sub — даже при одном инстансе; события ботов — через Valkey Stream (§10). Это дёшево сейчас и избавляет от переделок при масштабировании.

## 5. Авторизация (Keycloak)

### MVP — логин-пароль
1. Фронт (keycloak-js или oidc-client-ts) проходит **Authorization Code + PKCE** в realm'е vibe-chat.
2. Access JWT прикладывается к каждому REST-запросу; WS-handshake — через одноразовый ticket (см. ниже), а не напрямую JWT.
3. Бэкенд валидирует подпись по JWKS realm'а + `iss` / `aud` / `exp`; авторизация — по членству в чатах (см. «Права и роли» ниже), realm-роли в MVP не используются.
4. При первом входе бэкенд делает upsert локального пользователя по `sub` (см. §6).
5. Refresh-токен живёт только во фронтенде (silent refresh), бэкенд его не видит.

**Выбор фронтенд-библиотеки (этап 10): `oidc-client-ts` + `react-oidc-context`** — тонкая React-обёртка над стандартным OIDC client'ом; keycloak-js привязывает фронт к KC-адаптеру. Хранение токенов: память + `sessionStorage` (переживает reload вкладки; XSS-риск задокументирован — стандартный компромисс SPA). Silent refresh — через refresh token (silent-check iframe как fallback).

### Frontend-архитектура (этап 10)
- **Стек:** React 19 + TS + Vite; Tailwind CSS 4 + shadcn/ui; TanStack Query v5 (REST-кэш, query keys: `['chats']`, `['messages', chatId, ...]`, `['users']`); Zustand — WS-статус и живые события; `oidc-client-ts` — auth; `react-router` — маршруты.
- **WS-интеграция:** Zustand-стор принимает события WS и точечно обновляет TanStack Query cache (`setQueryData` для `message.new/edited/deleted`, `reaction.updated`, `read`; инвалидирует `['chats']` на изменениях состава). Typing — локальный стор (не Query). Дедупликация по message id; оптимистичная отправка — `client_ref` как temp-id, замена на серверный при подтверждении.
- **Realtime-протокол клиента:** ticket `POST /ws/ticket` → `WS /ws?ticket=`; reconnect с backoff; после reconnect — REST-догоняние (§9): `GET /chats` + `?after=`/`?updated_after=` по открытым чатам.
- **Реакции:** панель 5 эмодзи (`thumbs_up`/`heart`/`laugh`/`fire`/`check`) на hover/long-tap; toggle `PUT /messages/{id}/reactions`; optimistic toggle в кэше.
- **Время:** отображение по `users.time_display` (browser|as_sent|fixed|utc); для `as_sent` конверсия в `messages.timezone`; редактирование по окну — фронт считывает конфиг из ответа API (нет в MVP — константа 24 ч).
- **Страницы:** `/login` (redirect на KC), `/register` (инвайт-форма), `/` (список чатов), `/chat/:id`, `/settings` (профиль: персональные данные + time_display/timezone; платформенному админу — секции боты/инвайты).
- **API-клиент:** тонкий fetch-обёртка над `/api/v1` (Bearer из OIDC; 401 → silent renew → retry; WS ticket — отдельная функция).

**Выбор фронтенд-библиотеки (этап 10): `oidc-client-ts`** — framework-agnostic, активная поддержка, React-интеграция (`react-oidc-context`) тонкая и не тянет состояние в глобальный провайдер; keycloak-js привязывает приложение к KC-адаптеру и усложняет переход к стандартному OIDC. Токены — в памяти + `sessionStorage` (XSS-компромисс задокументирован; refresh rotation снижает риск). Silent refresh через iframe (default) + fallback на повторный логин.

### Разграничение: аутентификация vs персональные данные
Keycloak — **только identification/authentication**: он выдаёт стабильный `sub` и проверяет учётные данные (логин-пароль, в перспективе LDAP/Kerberos через федерацию). Все персональные данные пользователя — имя, фамилия, почта, отображаемое имя, аватар, часовой пояс — **хранятся и редактируются на уровне системы** (PostgreSQL vibe-chat, профиль через `PATCH /users/me`):

- Из JWT-клеймов не берётся ничего персонального: ни `name`, ни `given_name`/`family_name`, ни `email`. Клейм `preferred_username` используется только как **начальный** `username` при первом upsert (технический логин, не персональные данные) и дальше живёт в БД.
- Данные Keycloak и vibe-chat не синхронизируются: смена имени/почты в Keycloak не меняет профиль в системе и наоборот.
- Следствие: в realm Keycloak не заводится персональных атрибутов сверх стандартного профиля OIDC; федерация LDAP/Kerberos (§5 «Будущее») продолжает отвечать только за аутентификацию — `sub` стабилен, персональные данные остаются в БД системы.
- До профиля ключевые клеймы JWT: `sub`, `exp`, `iss`, `aud`. Остальные клеймы игнорируются.

### Регистрация пользователей (инвайт-коды)
Штатная self-registration Keycloak **выключена** (`registrationAllowed: false`) — её форма собирает персональные данные в KC, что нарушает разграничение выше. Регистрация — **инвайт-кодами**, реализуется на бэкенде/фронтенде системы:

- Коды выдаёт **платформенный админ** (`POST /invites`). Код **multi-use**: `max_uses` (NULL = безлимит — «дверной» код на отдел) + опциональный `expires_at`; можно деактивировать (`POST /invites/{id}/deactivate`). В БД хранится только sha256-хэш кода; сам код показывается один раз при создании (как токен бота).
- **Раздача кода — ссылкой** `/register?code=…` (этап 10.1): секретность обеспечивает сам код, ссылка лишь удобная его упаковка. Админ копирует готовую ссылку сразу после создания и отправляет тем, кто должен зарегистрироваться (почта/мессенджер). Форма регистрации предзаполняет код из query-параметра. Ссылка эквивалентна коду: перехвативший её получает тот же доступ, что и перехвативший код.
- Форма регистрации — на фронтенде vibe-chat (`POST /auth/register`, без аутентификации): инвайт-код, username, пароль **и персональные данные** (имя, фамилия, email, display_name) — последние сразу пишутся в PostgreSQL системы.
- Аккаунт в Keycloak создаёт бэкенд через **Admin API** (service-account client `backend-admin` с ролью `realm-management/manage-users`, grant `client_credentials`) — передаются **только username + password**, без `firstName`/`lastName`/`email`.
- Порядок: проверка кода (активен/не истёк/не исчерпан) → username свободен → создание в KC (409 KC → 409 клиенту; недоступен → 502) → **атомарное потребление кода** (conditional `UPDATE … WHERE uses_count < max_uses`; проигравший гонку получает компенсирующее удаление KC-аккаунта) + создание локального пользователя — в одной транзакции.
- Первый вход после регистрации — обычный OIDC-логин: JWT → JIT upsert находит уже созданного пользователя по `sub`, персональные данные сохраняются. Пароль проверяет Keycloak (политика паролей — настройка realm'а, локально минимум 8 символов).
- Без настроенного `APP_KEYCLOAK_ADMIN_CLIENT_SECRET` регистрация отвечает 503 (не настроена).

### WebSocket auth
Токен в query-параметре — плохая практика. Схема:
1. `POST /api/v1/ws/ticket` с JWT → одноразовый ticket (TTL 30 сек, хранится в Valkey).
2. `WS /api/v1/ws?ticket=...` → тикет сгорает при подключении. Удаление — атомарное (GETDEL), чтобы два параллельных подключения не прошли с одним тикетом.
3. Истечение access JWT во время жизни WS-соединения — норма: соединение не пере-валидируется; новое подключение требует новый ticket.

### Права и роли
В MVP realm-роли Keycloak не используются. Авторизация — на уровне членства в чатах: роль `owner`/`admin`/`member` в `chat_members` (права: admin — редактирование чата, добавление/удаление участников, удаление чужих сообщений; owner — дополнительно передача владения и удаление чата; у direct-чатов оба — member). Права на сообщение для автора: правка своего текста, удаление своего (soft delete). **Платформенный админ** (`users.is_platform_admin`) — отдельная сущность, к чатовой роли admin отношения не имеет: управляет ботами (создание, регенерация токена, деактивация). В MVP платформенный админ — первый seed-пользователь; post-MVP — realm-роль Keycloak.

### Будущее: LDAP и Kerberos
Реализуются **федерацией в Keycloak** (User Federation → LDAP, Kerberos/SPNEGO). Изменений в бэкенде и фронтенде не требуется — это ключевая причина выбора Keycloak. В MVP только следим, что `sub` стабилен при смене способа аутентификации.

## 6. Доменная модель

Боты и люди живут в одной таблице `users` (`is_bot`), чтобы membership и права не плодить в двух экземплярах.

### Таблицы

**users** — `id` UUID PK, `keycloak_sub` UUID UNIQUE NULLABLE (NULL у ботов — они не проходят через Keycloak; идентификация/аутентификация — Keycloak §5, персональные данные — здесь), `username` UNIQUE (при коллизии при upsert — суффикс), `display_name`, `first_name` NULLABLE, `last_name` NULLABLE, `email` NULLABLE (персональные данные живут только здесь, из JWT не берутся — §5), `avatar_file_id` → files, `is_bot` bool, `is_platform_admin` bool (платформенный админ: управление ботами; в MVP — первый seed-пользователь; признак хранится в БД, из клеймов JWT не берётся), `time_display` enum(`browser`,`as_sent`,`fixed`,`utc`, default `browser`) — режим отображения времени (см. «Время и часовые пояса»), `timezone` IANA-имя NULLABLE (пояс для режима `fixed`; также определяет эффективный пояс отправителя при записи сообщений), `is_active`, `created_at`, `last_seen_at` NULLABLE (момент закрытия последнего WS-соединения — источник last_seen в presence-событиях; у ботов и ни разу не подключавшихся — NULL).

**invites** — `id` UUID PK, `code_hash` UNIQUE (sha256; сам код `vh_…` показывается один раз при создании), `created_by` → users (платформенный админ), `max_uses` INT NULLABLE (NULL = безлимит), `uses_count` INT (default 0), `expires_at` NULLABLE, `deactivated_at` NULLABLE, `created_at`. Потребление — атомарно (conditional UPDATE, §5 «Регистрация»).

**bot_profiles** — `user_id` PK/FK→users, `owner_user_id` (кто создал), `description`, `token_hash` (только sha256), `miniapp_url`, `miniapp_name` (каркас под mini-apps), `webhook_url` (post-MVP).

**chats** — `id` UUID, `type` enum(`direct`, `group`), `title` (для group), `avatar_file_id`, `created_by`, `created_at`, `deleted_at` NULLABLE (soft delete чата). Для direct-чатов — служебная таблица `direct_chat_keys` (`user_a`, `user_b` — отсортированные ID, UNIQUE) → `chat_id`, чтобы пара не могла породить два чата. У direct-чатов в MVP оба участника имеют роль `member`; выход и удаление direct-чата не поддерживаются (скрытие чата — post-MVP). Direct с самим собой (self-chat «избранное») в MVP не поддерживается: `POST /chats/direct` со своим `user_id` → 422.

**chat_members** — PK (`chat_id`, `user_id`), `role` enum(`owner`,`admin`,`member`), `joined_at`, `last_read_message_id` (основа read receipts в MVP), `last_read_at`. Права ролей: owner — всё; admin — редактирование чата (название), добавление/исключение участников, назначение/снятие `admin` у `member`; member — чтение и отправка. Owner назначает/снимает admin; admin не трогает админов и owner'а; смена ролей — `PATCH /chats/{id}/members/{user_id}` `{role}` (§12, этап 12).

**messages** — `id` **UUIDv7** (монотонность по времени → простая пагинация и сортировка), `chat_id`, `sender_id` → users **NULLABLE (NULL у system-сообщений)**, `type` enum(`text`,`system`) — медиа-тип живёт только в `attachments.kind` (см. §7), `text`, `payload` jsonb NULLABLE (параметры system-сообщений: кто добавил/исключил, новое название и т.п.; у text-сообщений NULL), `client_ref` UUID (идемпотентность отправки: клиент передаёт в заголовке `Idempotency-Key` или в теле; при ретрае с тем же ключом сервер возвращает уже созданное сообщение, а не создаёт дубль; UNIQUE по `(sender_id, client_ref, chat_id)` — одно действие = один ключ, включая forward в несколько чатов), `reply_to_id` → messages NULL (цитирование), `forward_from_message_id`, `forward_from_chat_id`, `forward_snapshot` jsonb (денормализованные имя автора, время и пояс оригинала — пересылка переживает удаление источника), `created_at`, `updated_at` (растёт при edit и soft delete — курсор догоняния изменений), `timezone` IANA-имя NULLABLE (эффективный пояс отправителя в момент отправки: клиент передаёт, сервер валидирует по списку IANA, невалидный → NULL; у ботов и system-сообщений NULL), `edited_at`, `deleted_at` (soft delete). Индекс `(chat_id, id)` — главный индекс системы.

**attachments** — `id`, `message_id`, `file_id`, `kind` enum(`image`,`video`,`file`) — единственный источник правды о типе медиа, `file_name`, `width`, `height`, `duration_ms` (клиентские метаданные для UI). `thumb_key`/`blurhash` живут в `files` (см. ниже) — они генерируются при `complete`, до создания какого-либо attachment'а. При создании сообщения сервер сверяет `kind` с `files.real_mime_type` (image/* → kind=image, video/* → kind=video, иное → file); несовпадение — 422, а не тихий рассинхрон.

**files** — `id` UUID, `status` enum(`pending`,`ready`), `bucket`, `storage_key` (в Silo), `size_bytes`, `mime_type` (заявленный клиентом), `real_mime_type` (определён сервером при `complete`), `thumb_key` NULLABLE, `blurhash` NULLABLE (оба заполняются при `complete` для image), `sha256` (целостность/аудит; дедупликация — post-MVP), `uploader_id`, `created_at`.

**reactions** — `message_id` PK/FK→messages, `user_id` PK/FK→users (составной PK: одна реакция на пользователя на сообщение), `emoji` (короткое имя из фиксированного набора — `thumbs_up`, `heart`, `laugh`, `fire`, `check`; рендерит фронт), `created_at`. Реакция — **не** сообщение: в ленту не пишется, `updated_at` сообщения не двигает (в дельту edit/delete не попадает; доставка — WS-событие `reaction.updated`). Удаление сообщения скрывает реакции вместе с надгробием, строки не удаляет.

**calls** — `id` UUIDv7 PK (= имя комнаты LiveKit, §17), `chat_id` → chats, `initiator_id` → users, `kind` enum(`audio`,`video`) — видео с этапа C без миграций, `status` enum(`ringing`,`active`,`ended`), `created_at`, `started_at` NULLABLE (первый accept/join), `ended_at` NULLABLE. Индекс `(chat_id, created_at)` — история звонков чата.

**call_participants** — PK (`call_id`, `user_id`), `joined_at` (первый вход; повторные входы/выходы группового звонка — в лог не пишем, только текущее состояние), `left_at` NULLABLE. Звонок завершается, когда `active` и не осталось участников с `left_at IS NULL`; «пропущенный» у неответивших — дериват статуса звонка и `call_participants` (не отдельная таблица).

### Доступ к файлам
- `pending` — видит только uploader; доступ к содержимому появляется после прикрепления к сообщению (участники этого чата) либо при использовании как аватар (все активные пользователи).
- Право чтения определяется членством в чате, к которому прикреплён файл, — не «загрузил, значит можешь читать».
- Аватары (`users.avatar_file_id`, `chats.avatar_file_id`) видят все активные пользователи; замена аватара не удаляет старый файл (cleanup соберёт отсроченно — см. ниже), чтобы старые сообщения с этим аватаром не ломались.
- Cleanup: периодическая задача удаляет `pending`-файлы старше 24 ч (строка в БД + объект в Silo); а также `ready`-файлы, не прикреплённые ни к одному сообщению, не являющиеся ничьим текущим аватаром и не используемые ни в одном `attachments`, старше N дней (конфиг, по умолчанию 7) — иначе брошенные после `complete` загрузки копятся в Silo вечно. Cleanup **не удаляет** файлы, на которые ссылаются существующие сообщения, — даже после их soft delete (история должна рендериться).

### Удаление сообщений
Soft delete (`deleted_at`); в чате отображается «сообщение удалено». Политика — **«удалять у всех»** (решено 2026-11-11): удаление для всех участников, per-user скрытия нет.

### Удаление и выход
Group: участник выходит через `DELETE /chats/{id}/members/{me}`; чат-админ исключает участников; **owner'а нельзя исключить и owner не может выйти, не передав владение** (`POST /chats/{id}/owner` — передача владения). Direct: выход/удаление не поддерживаются в MVP (скрытие — post-MVP).
Удаление чата (`DELETE /chats/{id}`, owner, только group) — soft delete чата (`chats.deleted_at`); в списках `GET /chats` удалённые не возвращаются; сообщения не удаляются физически. Передача владения (`POST /chats/{id}/owner`): бывший owner становится `admin`, новый — `owner`. Бот при исключении из чата теряет доступ к содержимому (включая presigned-URL и чтение истории), его сообщения в чате остаются видимыми участникам.

### Деактивация пользователя
`is_active=false` (увольнение сотрудника): вход через Keycloak отклоняется (бэкенд отклоняет токены с `sub` деактивированного), WS-соединения рвутся, токены ботов, созданных этим пользователем как платформенным админом, отзываются. Написанное ранее — остаётся: сообщения и файлы не удаляются. Реализация — post-MVP: в MVP деактивация выполняется вручную в Keycloak (disable user) + `is_active=false` в БД вручную.

### Редактирование сообщений
`PATCH /messages/{id}` — только **автором**, только **текст** (`text`) и только пока сообщение без attachments (медиа не редактируется: файлы неизменяемы по design'у). Окно редактирования — конфиг (по умолчанию 24 ч). При изменении: `edited_at` + событие `message.edited`. Ботам редактирование недоступно в MVP полностью (см. §10, send-only).

### Правила рендера медиа
Единственный источник типа — `attachments.kind`: ровно один image-attachment → инлайн-картинка (поле `text` = подпись); video/file → карточка с иконкой, именем, размером. Несколько image-attachments — галерея.

### Реакции
Эмодзи-реакции на сообщения (решено 2026-11-11, добавлено в MVP): фиксированный набор эмодзи (`thumbs_up`, `heart`, `laugh`, `fire`, `check`) — панелька над/под сообщением в UI. `POST /messages/{id}/reactions {emoji}` (toggle: повторный — снимает), `DELETE /messages/{id}/reactions` (явное снятие), реакции в сериализации сообщения (`reactions: [{emoji, user_ids}]` — без имён, фронт уже имеет список участников чата). Событие WS `reaction.updated {message_id, chat_id, reactions}` — всему чату. Только участники чата; только text-сообщения (на system/удалённые нельзя). Реакции не двигают `updated_at` сообщения.

### Системные сообщения
`messages.type=system` пишутся в ленту чата при: создании группового чата, смене названия/аватара, добавлении/исключении участника, выходе, передаче владения, удалении чата (финальное). `sender_id` NULL у system-сообщений (автор — система, не пользователь); параметры события — в `payload` jsonb (кто/что/новое значение — фронт рендерит локализованную строку). Системные сообщения **нельзя цитировать, пересылать и редактировать**. Событие `member.left` в WS — уведомление о выходе; в ленте при этом появляется system-сообщение. Изменения состава и названия реализованы (этап 12): `rename_group`/`add_members`/`remove_member`/`transfer_ownership`/`set_member_role` пишут system-сообщение (`payload.kind` = `rename`|`member_added`|`member_removed`|`member_left`|`owner_changed`|`role_changed`) и публикуют `chat.updated`/`member.joined`/`member.left`.

### Идентификация сообщений
`messages.id` (UUIDv7) генерирует **бэкенд при вставке** — это единственный идентификатор сообщения в API, WS-событиях и ссылках (`reply_to_id`, `forward_from_message_id`, `attachments.message_id`). Клиент id не выбирает. Монотонность v7 делает id курсором пагинации: keyset по индексу `(chat_id, id)` без OFFSET; `created_at` — только для отображения. `client_ref` — не идентификатор, а ручка идемпотентности: по нему клиент связывает черновик с созданным сообщением (значение приходит в ответе и WS-событии). Риск коллизии случайных битов v7 в одну миллисекунду пренебрежим и ловится PK-констрейнтом.

Per-chat `seq_id` в MVP **не вводится**: строгий порядок внутри одной миллисекунды обеспечивает монотонный режим генератора UUIDv7 (счётчик, например пакет `uuid6`) — при одном инстансе бэкенда это честный total order. Если при переходе на несколько инстансов понадобится серверный номер сообщения, колонка добавляется аддитивно с бэкфиллом `ROW_NUMBER() OVER (PARTITION BY chat_id ORDER BY id)` — миграция некритичная.

### Время и часовые пояса
Все времена в БД и API — **UTC**: `timestamptz`, в JSON — ISO 8601 с суффиксом `Z`. Единственный источник времени — сервер: клиентские часы в порядок не влияют, время сообщения клиент не передаёт. UUIDv7 кодирует Unix ms (UTC), поэтому порядок сообщений — по факту прихода на сервер: сообщение из «вечернего Владивостока» встанет раньше «московского дня», если пришло раньше.

**Пояс отправителя хранится в сообщении**: `messages.timezone` (IANA-имя, NULLABLE) — эффективный пояс отправителя в момент отправки (профильный `timezone`, иначе локальный браузерный). Клиент передаёт его при отправке; сервер валидирует по списку IANA (`zoneinfo.available_timezones()`), невалидный → NULL. У ботов и system-сообщений — NULL. Назначение: время «как отправлено» не плывёт при смене пользователем пояса; в перспективе — автозаполнение профиля при первом входе с мобильного приложения.

**Режимы отображения** (`users.time_display`):
| Режим | Что показывает |
|---|---|
| `browser` (по умолчанию) | локальное время смотрящего |
| `as_sent` | время в поясе конкретного сообщения (`messages.timezone`; NULL → браузерное) |
| `fixed` | фиксированный пояс из `users.timezone` |
| `utc` | UTC |

Пояса — только IANA-имена (не фиксированные offset'ы), чтобы DST обрабатывался корректно. Порядок сообщений от поясов не зависит никак.

## 7. Сообщения: цитирование, пересылка, вложения

- **Цитирование** = ответ (`reply_to_id`), без тредов. Фронт рендерит сниппет цитируемого сообщения (id + текст + автор). Треды — не в требованиях, не проектируем. Валидация при отправке: цель `reply_to_id` — сообщение **того же чата** (иначе 422), не system-сообщение; цитата удалённого сообщения рендерится как «сообщение удалено».
- **Пересылка**: выполняется только через `POST /messages/{id}/forward` (в список chat_ids; источник — чат, где пересылающий состоит, иначе 403). Вся операция атомарна: либо копии во **все** целевые чаты, либо ничего (ошибки валидации любого чата — 422 без частичного эффекта). В `POST /chats/{id}/messages` поля forward не принимаются. Копия сообщения с заполненным `forward_from_*` и `forward_snapshot`. Вложенные файлы при пересылке **копируются** (новые строки `files`/`attachments` — storage_key тот же), чтобы пересланное не ломалось при удалении оригинала. Пересылка пересланного — по тем же правилам: `forward_from_*` ссылается на непосредственный источник, отображаемый автор берётся из `forward_snapshot`.
- **Смайлики**: нативный Unicode, пикер на фронте (emoji-mart или аналог). Бэкенду требуется только UTF-8 end-to-end — отдельной работы нет.
- **Фото**: сообщение с image-attachment рендерится в чате инлайн по presigned GET: сначала `files.thumb_key` + `files.blurhash` как placeholder, затем оригинал. Thumbnail генерирует бэкенд (Pillow) на этапе `complete` загрузки. SVG не считается изображением (см. §8) — это file-attachment.
- **Видео в MVP**: attachment с иконкой/именем/размером. Метаданные (`width`, `height`, `duration_ms`) извлекает **клиент до загрузки** (HTMLVideoElement) — сервер без ffmpeg видео не декодирует; значения — только для UI. Превью-кадр и инлайн-плеер — post-MVP (ffmpeg на `complete` либо клиентский canvas-кадр).
- **Файлы**: скачивание по presigned GET; ограничение размера — конфигом.

## 8. Файлы (Silo)

Загрузка (без проксирования через бэкенд):
1. `POST /api/v1/files/upload-url` `{size, mime, sha256}` → presigned PUT + `file_id` (статус `pending`). sha256 считает клиент (WebCrypto); presigned PUT подписывается на публичный host (как GET) — он входит в подпись.
2. Клиент (или бот) кладёт файл в Silo напрямую.
3. `POST /api/v1/files/{id}/complete` → бэкенд HEAD'ом проверяет объект (реальный размер и mime — sniffing, не доверяем заявленным), для image генерирует thumbnail (Pillow), статус `ready`. Повторный `complete` по уже `ready`-файлу — идемпотентен (возвращает успех, повторных операций не делает); `complete` чужого файла — 403. Бакет `vibe-files` — гарантируется деплоем (скрипт инициализации Silo).

Выдача: presigned GET URL (thumb + оригинал, TTL ~1 ч) **встраиваются прямо в сериализацию сообщений/вложений** — не отдельным запросом на каждое вложение. При 403 от Silo (протухшая подпись) фронт точечно освежает URL через `GET /files/{id}/url`, а не перезапрашивает историю. `GET /files/{id}/url` остаётся для точечных случаев (аватар, превью перед отправкой, освежение).

Безопасность раздачи (файлы пользовательские — доверять нельзя):
- Silo отдаётся на **отдельном origin** (subdomain), чтобы куки/JS-origin SPA не действовали на файлах.
- presigned GET задаёт `response-content-disposition`: `inline` — только для реальных `image/*` (кроме SVG) и `video/*`; всё остальное — `attachment` (download). SVG считается file-attachment (может содержать скрипты).
- Mime определяется на сервере при `complete` (sniffing + Pillow probe), а не берётся из заявленного клиентом.
- **CORS обязателен**: браузерный PUT в Silo — cross-origin fetch (SPA-origin → Silo-origin, отдельные subdomain'ы и в prod, и в dev) — без `Access-Control-Allow-Origin` на Silo все загрузки падают на preflight. Отображение через `<img>`/`<video>` CORS не требует — поэтому проблема всплывёт только при первой загрузке. Настраивается переменными Silo (наследие MinIO `MINIO_API_CORS_ALLOW_ORIGIN`).

Именование в коде и конфигах: **Silo / SILO_***. Исключение — совместимые переменные окружения самого Silo, которые исторически называются `MINIO_*` (это нормально, но SDK конфигурируем через `endpoint_url`).

## 9. Realtime (WebSocket)

### Транспорт
Один WS на **соединение** (вкладка/устройство); у одного пользователя допустимо несколько одновременных соединений — каждое проходит свой ticket-обмен (см. §5). Формат — JSON-конверт:

```jsonc
// сервер → клиент
{ "type": "message.new", "data": { ... }, "event_id": "uuid", "ts": 1730000000.5 }
// клиент → сервер
{ "type": "typing", "data": { "chat_id": "..." } }
```

Client→server по WS — **только `typing`** (и ничего больше): все мутации (`read`, отправка, edit/delete, управление чатами) идут через REST — единая точка валидации, идемпотентности и прав. Незнакомые типы client→server игнорируются (лог), соединение не рвётся.

### События MVP
`message.new`, `message.edited`, `message.deleted`, `reaction.updated` (эмодзи-реакции, §6), `chat.created`, `chat.updated` (включая признак `deleted` при удалении чата), `member.joined`, `member.left`, `typing`, `presence` (online/offline/last_seen), `read` (сервер → клиентам: кто/до какого message_id прочитал). `event_id` — лог-поле для отладки, семантики курсора не имеет. Ботам из этого списка доставляются только `message.*` (§10).

Форматы `data` (контракты — §12; этап 10.2): `message.new/edited/deleted` → `{message: <MessageOut>}` — **полная сериализация тем же serializer'ом, что REST** (включая `attachments` с presigned URL и `reactions`); клиент мержит событие в кэш по id сообщения. Ботам тот же payload кладётся в Stream **плоским** словарём (без обёртки `{message: …}`). `reaction.updated` → `{message_id, chat_id, reactions}`; `chat.created`/`chat.updated` → `{chat: <ChatOut>}` (при удалении чата — с `deleted: true`); `member.joined` → `{chat_id, user: <UserOut>}`; `member.left` → `{chat_id, user_id}`; `typing` → `{chat_id, user_id}`; `presence` → `{user_id, online, last_seen_at}`; `read` → `{chat_id, user_id, last_read_message_id}`.

### Доставка и восстановление
- Fanout: бэкенд публикует событие в Valkey Pub/Sub (`chat:{id}` **и** персональный `user:{id}` каждого участника, этап 10.2); каждый инстанс подписан и рассылает своим соединениям. Персональный канал обязателен: WS-подписки на чаты формируются при коннекте, а чат мог появиться после него — без `user:{id}` сообщение в новый чат не дойдёт до открытой вкладки. Доставка — только текущим участникам на момент публикации: исключённый/вышедший участник и участники soft-deleted чата события больше не получают (о самом удалении чата каждому участнику разово доставляется `chat.updated` с признаком `deleted`). Гонка «отправка vs исключение» разрешается атомарной проверкой membership в той же транзакции, что и вставка сообщения: не участник — 403, третьего состояния нет. При одном инстансе это работает так же.
- Presence и typing рассылаются только тем, кто состоит с пользователем в одном чате, — иначе на 1k пользователей получится шторм событий (typing — в `chat:{id}`; presence — в `user:{id}` **всех «соседей по чатам»**, этап 10.2).
- Реконнект: клиент переподключается и **догоняет дельту через REST**: `GET /chats` (новые чаты, состав, `unread_count`) → для **каждого своего чата**: новые сообщения `GET /messages?after=…` и изменения (edit/delete) `GET /messages?updated_after=…` (по `messages.updated_at`); состояние прочтения других участников — из `GET /chats/{id}`. Фильтр «только изменённые чаты» требует per-chat курсора изменений (`last_message_at` не двигается при edit/delete) — в MVP вместо него запрашиваются все чаты (десятки на пользователя — дёшево). Без запроса `updated_after` правки, случившиеся офлайн, никогда не доехали бы до клиента. Очередь реплея на сервере в MVP не строим — REST-дельта проще и надёжнее. Дубликаты WS-событий (at-least-once) дедуплицируются фронтом по id сообщения.
- Presence: счётчик живых соединений пользователя — в Valkey (INCR при подключении, DECR при закрытии; DECR → 0 → бэкенд пишет `users.last_seen_at` и рассылает `presence` (offline + last_seen)). Счётчик в процессе бэкенда запрещён принципом «состояний в процессах нет» (§14). Ключ `presence:{user_id}` с TTL ~60 сек (пингуется соединениями) — страховка на нечистое закрытие (падение инстанса): истечение TTL замечается отложенно (до ~60 сек) и даёт тот же offline-эффект.
- Read receipts: клиент вызывает `POST /chats/{id}/read` (канонический путь) → бэкенд обновляет `chat_members.last_read_message_id` → событие `read` участникам.
- Звонки (этапы A/B/C, §17): сигналинг звонка — события `call.ring`, `call.accepted`, `call.rejected`, `call.cancelled`, `call.joined`, `call.left`, `call.ended` поверх этого же WS (форматы — §17); медиа-сигналинг (SDP/ICE) идёт мимо бэкенда — напрямую в LiveKit по room-токену.

## 10. Боты

- Бот — строка в `users` (`is_bot=true`) + `bot_profiles`. Создаётся **только платформенным админом** (в MVP платформенный админ — первый seed-пользователь, см. §5) через REST `/bots` (§12) — в MVP достаточно Swagger/простой админ-страницы, отдельный UI управления — post-MVP.
- Токен: `vbt_<random>`, выдаётся один раз при создании, хранится только sha256-хэш. Авторизация: `Authorization: Bearer vbt_...` — та же мидлварь распознаёт префикс и переключается на bot-контекст. Регенерация: `POST /bots/{id}/token/regenerate` (админ) — старый токен отклоняется сразу, новый выдаётся в ответе; зависший на старом токене long polling завершается немедленно (409). Деактивация (`is_active=false`) — чтобы утечка токена не была тупиком: токен отклоняется сразу, зависший long polling завершается немедленно (409), bot-Stream удаляется.
- Права: бот действует только в чатах, куда добавлен как участник (обычные membership-проверки). В чаты бота добавляет чат-админ так же, как обычного пользователя (боты находятся обычным `GET /users?q=`). Боты разрешены и в direct-чатах (основной сценарий). В MVP бот может только отправлять сообщения; edit/delete сообщений ботом — не поддерживается.
- **Получение событий в MVP — long polling**: `GET /api/v1/bot/updates?offset=...&timeout=30`. Offset — Valkey Stream ID; события буферизуются в персональном Stream бота с retention 24 ч. Если offset старше retention (бот был офлайн) → ответ `{resync: true}`, бот делает полный resync: `GET /bot/chats` + сообщения. Боту доставляются только события его чатов и только `message.new/edited/deleted` (включая system-сообщения как `message.new` с `type=system`), `member.joined/left` — **presence и typing ботам не доставляются** (не нужны и дороги). При исключении бота из чата в его Stream доставляется финальное `member.left`; после деактивации зависший poll завершается немедленно (409). Не нужен публичный URL и инфраструктура ретраев — самый дешёвый MVP-вариант.
- Вебхуки (`webhook_url` + retry-очередь) — post-MVP.
- Bot API (MVP): `GET /bot/me`, `GET /bot/chats`, `GET /bot/chats/{id}/messages?before=|after=` (история + основа resync), `GET /bot/updates`, `POST /bot/messages` (текст/фото/файл, reply, forward; идемпотентность через `Idempotency-Key` / `client_ref`). Загрузка файлов ботами — тот же presigned-флоу, что у людей (§8).

## 11. Mini-apps (каркас в MVP, реализация post-MVP)

Концепция (в стиле Telegram mini-apps): веб-приложение, привязанное к боту, открывается внутри интерфейса чата (iframe) — меню бота / кнопка в шапке чата.

Auth handoff:
1. Фронт открывает iframe `miniapp_url`.
2. Фронт запрашивает у бэкенда one-time код: `POST /api/v1/miniapps/{bot_id}/code` (JWT-авторизация; разрешено, только если пользователь состоит в каком-либо чате с этим ботом) и передаёт его в iframe через `postMessage` — с обязательной проверкой `event.origin` против `miniapp_url`.
3. Mini-app меняет код на скоупед opaque-токен: `POST /api/v1/miniapps/token` → далее обычный REST.
4. Код одноразовый (TTL 60 сек, привязан к user + miniapp). Токен `mat_<random>` — единственный случай, когда бэкенд выдаёт токен сам (явное исключение из §4): TTL 15 мин, без refresh, скоуп «действовать от имени пользователя только в этом miniapp»; продление — только через повторный handoff. Хэш токена — в Valkey.
5. `miniapp_url` — только HTTPS; origin хранится рядом с URL и сверяется при handoff.

**В MVP делаем только каркасы**: поля `miniapp_url` / `miniapp_name` в БД, эндпоинты-заглушки (код + обмен), контракт `postMessage` в этом документе. Никакого UI запуска mini-apps.

## 12. Эскиз REST API (/api/v1)

```
# Пользователи
POST   /auth/register              # инвайт-регистрация: {invite_code, username, password, персональные данные} (§5) — без аутентификации
GET    /users/me
PATCH  /users/me                   # display_name, first_name, last_name, email, аватар, time_display, timezone — персональные данные только здесь (§5)
GET    /users?q=                   # поиск (люди и боты, флаг is_bot в ответе) для чатов/участников
GET    /users/{id}

# Инвайты (платформенный админ)
POST   /invites                    # {max_uses?, expires_at?} → {code} (код показывается один раз)
GET    /invites                    # список с uses_count
POST   /invites/{id}/deactivate

# Чаты
POST   /chats                      # групповой; {title, member_ids[]} (creator = owner; member_ids ≥ 1, creator в списке игнорируется, боты допустимы)
POST   /chats/direct               # {user_id} → создать/вернуть существующий direct с пользователем
GET    /chats                      # включая last_message_at (вычисляется из MAX(id), в схеме не хранится), unread_count
GET    /chats/{id}                 # чат + участники (роль, last_read_message_id, объект user — нужен фронту для имён direct-чатов, этап 10.2)
PATCH  /chats/{id}                 # title, avatar (admin/owner)
DELETE /chats/{id}                 # весь чат (owner, только group)
POST   /chats/{id}/members         # {member_ids: [...]} (admin/owner); уже состоящие пропускаются — идемпотентно
POST   /chats/{id}/owner           # передача владения (owner)
DELETE /chats/{id}/members/{user_id}   # только group; выход = DELETE своего user_id; owner — сначала передача владения; не-участник — 404
PATCH  /chats/{id}/members/{user_id}   # {role: admin|member} — назначение/снятие чат-админа (owner; этап 12)
POST   /chats/{id}/read            # {message_id} — сообщение этого чата; курсор двигается только вперёд (MAX, не откатывается)

# Сообщения
GET    /chats/{id}/messages?before=|after=|updated_after=|around=&limit=50   # after — новые; updated_after — edit/delete-дельта для реконнекта (soft-deleted возвращаются как заглушки); around — переход к цитате
POST   /chats/{id}/messages        # text / attachments / reply_to + Idempotency-Key + timezone (forward — только через /messages/{id}/forward)
PATCH  /messages/{id}              # только text, только автор, окно — конфиг
DELETE /messages/{id}                # автор — свой; admin — чужие (soft delete)
POST   /messages/{id}/forward      # {chat_ids: [...]} + Idempotency-Key

# Реакции
PUT    /messages/{id}/reactions    # {emoji} — toggle: поставить/снять свою (решено 2026-11-11)

# Файлы
POST   /files/upload-url
POST   /files/{id}/complete
GET    /files/{id}/url             # точечные случаи; в сообщениях URL встроены в сериализацию

# Звонки (§17, этапы A/B/C)
POST   /calls                      # {chat_id, kind: audio|video} → CallOut (require_member; direct — сразу ringing)
POST   /calls/{id}/accept          # direct: ответил → status=active, call.accepted
POST   /calls/{id}/reject          # direct: отказался → call.rejected; initiator может cancel
POST   /calls/{id}/cancel          # direct: initiator отменяет до accept → call.cancelled
POST   /calls/{id}/join            # group (и повторный вход direct при реконнекте): статус → active
POST   /calls/{id}/leave           # выход участника; последний вышел → ended
POST   /calls/{id}/token           # room-токен LiveKit для этого звонка (только участник чата; TTL ~10 мин)

# WS
POST   /ws/ticket
WS     /ws?ticket=

# Боты (Bearer vbt_...)
GET    /bot/me
GET    /bot/chats
GET    /bot/chats/{id}/messages?before=|after=   # история + основа resync
GET    /bot/updates?offset=&timeout=30
POST   /bot/messages

# Управление ботами (JWT, платформенный админ)
GET    /bots                       # список ботов
POST   /bots                       # {username, display_name, description} → ответ содержит vbt_-токен один раз
POST   /bots/{id}/token/regenerate
PATCH  /bots/{id}                  # description, is_active

# Mini-apps (каркас)
POST   /miniapps/{bot_id}/code     # one-time код (JWT-авторизация)
POST   /miniapps/token             # обмен кода на mat_-токен
```

## 13. Деплой и конфигурация

`docker-compose.yml` сервисы: `backend`, `frontend` (nginx + собранный SPA), `postgres`, `valkey`, `silo`, `keycloak`; с этапа A звонков (§17) — `livekit` (один контейнер, без Redis при одной ноде) и `coturn` (TURN-fallback).

Топология: nginx — единая точка входа: раздаёт SPA, проксирует `/api/v1/*` (REST и WS с upgrade-заголовками) на backend. CORS в prod не нужен (same origin); в dev — vite proxy на backend. Keycloak и Silo — на отдельных subdomain'ах (Silo — обязательно, см. §8).

- Вся конфигурация бэкенда — переменными окружения, префикс `APP_*` (pydantic-settings); `.env.example` — источник правды по составу. Для Silo два адреса: `SILO_INTERNAL_URL` (compose-сеть: HEAD при `complete`, чтение исходника thumbnail'а) и `SILO_PUBLIC_URL` (хост, зашиваемый в presigned URL — он входит в подпись и должен совпадать с тем, по которому ходит клиент).
- Бэкапы (дефолт до уточнения у заказчика, §16): ежедневный `pg_dump` по расписанию (ночь, retention 14 дней) + снапшоты тома Silo; скрипты в `deploy/backup/`.
- Keycloak: realm `vibe-chat` описывается realm-export'ом в `deploy/keycloak/`, чтобы поднимался воспроизводимо. В client-конфиге обязателен **audience mapper** (backend-api в `aud`), иначе строгая валидация `aud` на бэкенде отвергнет все токены; redirect URIs зависят от окружения — параметризовать или держать вариант файла на окружение.
- Dev-режим: `uvicorn --reload` и `vite` отдельно от compose-инфраструктуры (postgres/valkey/silo/keycloak в compose, приложения локально).
- LiveKit (§17): порты `7880/tcp` (WebSocket-сигналинг), `7881/tcp` (TCP-fallback ICE), `50000–60000/udp` (медиа, должен быть открыт на хосте — это главное требование к VPS), `443/udp` (TURN TLS). `rtc.use_external_ip: true` — сервер с выделенным IP достижим клиентами за NAT напрямую (исходящий UDP от клиента); coturn (TLS :443) — fallback для сетей с зарубленным UDP. TURN-сертификат — на отдельное DNS-имя (turn.*), валидный TLS обязателен.

## 14. Масштабирование (заделы, не задачи MVP)

- Состояния в процессах нет: сессии WS можно раздавать по N инстансам за reverse-proxy, fanout уже через Valkey.
- Presigned-загрузки не нагружают бэкенд.
- Первое реальное узкое место — PostgreSQL: партиционирование `messages` по времени + индекс `(chat_id, id)`.
- Valkey: Pub/Sub для WS fanout и Streams для бот-обновлений используются с первого дня (см. §4, §10). При росте — consumer groups для горизонтальной обработки.

## 15. Дорожная карта

**MVP (по порядку):**
1. Скаффолдинг монорепо + compose-инфраструктура (postgres, valkey, silo, keycloak, realm-export с audience mapper) + инструментарий: ruff, mypy, pytest (backend), vitest (frontend), pre-commit. CI — открытый вопрос §16.
2. Интеграция Keycloak, валидация JWT, upsert пользователей.
3. Чаты: direct/group, участники, поиск пользователей.
4. Сообщения: текст, вложения (фото инлайн, файлы), emoji, цитирование, пересылка, идемпотентность (`Idempotency-Key`), пояса (`messages.timezone` + режимы `time_display`).
5. Realtime: WS (tickets), typing, presence, read receipts.
6. Файловый cleanup: `pending` старше 24 ч + брошенные `ready` (не прикреплены, не аватары) старше N дней.
7. Боты: токены, Bot API, long polling, регенерация токена.
8. Каркас mini-apps (без UI).
9. Реакции на сообщения: таблица `reactions`, toggle-API, WS-событие `reaction.updated`, UI-панель (решено 2026-11-11).
10. Фронтенд: логин Keycloak, список чатов, лента сообщений (вложения, реакции, цитирование, пересылка), realtime (WS + догоняние), настройки профиля (time_display/timezone).
11. Инвайт-регистрация: multi-use коды платформенного админ, `POST /auth/register`, создание KC-аккаунта через Admin API (только username+password), персональные данные — в системе (§5).
12. Вложения в UI (этап 11, 2026-11-11): композер чата — скрепка → выбор файла → upload-флоу §8 (sha256 считает клиент), карточка вложения в композере, отправка `attachments` вместе с текстом; визуально — фото инлайн, файлы/видео карточкой (§7).
13. Управление группой и пересылка в UI (этап 12, 2026-11-13): переименование `PATCH /chats/{id}` (admin/owner) + system-сообщение; смена ролей `PATCH /chats/{id}/members/{user_id}` `{role}` (owner); system-сообщения и `member.joined/left`/`chat.updated` при всех изменениях состава; UI — диалог «Инфо о группе» (участники/роли/добавление/исключение/передача владения), «Переслать» в меню сообщения (мультивыбор чатов).

**Звонки (проработано 2026-11-13, §17; вне MVP-нумерации):**
A. Аудио 1:1 (direct) — **реализовано (2026-11-13)**: compose + LiveKit (coturn — при деплое на VPS, открытый вопрос §16); таблицы `calls`/`call_participants`; REST `/calls/*` + room-токен; WS-события `call.*`; ringing-UI (overlay, звук WebAudio), панель активного звонка (таймер/mute/hang-up); system-сообщения «Звонок / Пропущенный»; cleanup ringing 45 сек.
B. Групповые аудио: join-модель (room без ринга каждому — как Telegram), список участников в звонке, групповой UI; схема БД и REST из A переиспользуются (join/leave уже реализованы — нужен только UI).
C. Видео: публикация камеры (simulcast — в SFU из коробки), плитки видео, шаринг экрана; тот же контур, другой UI.

**Post-MVP:** инлайн-видео, вебхуки ботов, mini-apps (UI + запуск), LDAP/Kerberos (федерация Keycloak), поиск по сообщениям (PG full-text), мобильные приложения, push-уведомления.

## 16. Открытые вопросы (не блокируют концепцию)

**Решено 2026-11-11:**
- UI-кит и data layer фронтенда — **Tailwind CSS + shadcn/ui; TanStack Query + Zustand** (§2).
- CI — **отложен**: локальные проверки (ruff/mypy/pytest, oxlint/tsc/vitest); вернуться при появлении второй площадки разработки.
- Реакции на сообщения — **добавлены в MVP** (§6 «Реакции», §12).
- Политика удаления сообщений — **«удалять у всех»** (§6).
- Уведомления — **отложены** (post-MVP, вместе с мобильными).
- Требования к хранению и бэкапам — **дефолт до уточнения у заказчика**: ежедневный `pg_dump` (ночь, retention 14 дней) + зеркалирование/снапшот тома Silo; скрипты — в `deploy/`.
- Лимиты §8/§9 — **дефолты в конфиге**: max 10 вложений на сообщение, max 100 МБ/файл, длина текста 40 000, антифлуд 20 сообщений/мин на пользователя, typing не чаще 1 раза в 2 сек, max 20 chat_ids в одном forward.
- Звонки — **выбран LiveKit self-hosted** (2026-11-13, §17): SFU вместо P2P-mesh (NAT, групповые), один контейнер compose, room-токен — скоупед JWT (третье исключение из «бэкенд не выдаёт токены», §17).

**Остались открытыми:**
- Хостинг/заказчик для production-окружения (где живёт compose, домены Keycloak/Silo).
- TURN-домен и TLS-сертификат для coturn (нужно DNS-имя turn.* и валидный сертификат — зависит от выбора хостинга, §17).

## 17. Звонки (аудио/видео; этапы A/B/C — проработано 2026-11-13, реализация вне MVP)

### Архитектура: SFU LiveKit, не P2P

Медиа-сервер — **self-hosted LiveKit** (Go-SFU, Apache 2.0, один бинарь/контейнер). Выбор против альтернатив:

- **Не P2P-mesh**: hole-punching через NAT срабатывает лишь в 60–80% случаев (STUN без TURN — не решение, а надежда); mesh не масштабируется на группы (6 участников = 5 исходящих потоков у каждого); вся логика ICE/реконнектов дублируется в клиентах. SFU снимает все три проблемы: клиент инициирует исходящее соединение к серверу с выделенным IP (работает за любым NAT, где разрешён исходящий UDP), групповой звонок — та же механика, что 1:1.
- **Не Jitsi**: готовый продукт (встраивается только iframe'ом — чужой UX, XMPP-стек из 4+ контейнеров), нам нужен движок под свой UI.
- **Не mediasoup**: библиотека-движок без сигналинга/SDK — сигналинг, room-менеджмент, клиенты пришлось бы писать самому (недели-месяцы). LiveKit даёт всё из коробки при том же контейнере.

Разделение сигналинга (принцип «бэкенд медиа не проксирует», как с Silo):
- **Сигналинг звонка** (кто кому звонит, ринг, accept/reject, состав) — наш: REST-мутации + WS-события `call.*` через существующий fanout (§9).
- **Медиа-сигналинг** (SDP/ICE, треки) — клиент напрямую в LiveKit (WS :7880) по room-токену; бэкенд его не видит.

Нагрузка при масштабе MVP (~1k пользователей, звонки — единицы одновременных): одна нода LiveKit без Redis (Redis нужен только для кластера из нескольких нод), аудио ~30 kbps на участника на каждого слушателя (звонок на 10 человек ≈ 3 Мбит/с egress).

### Модель звонков

- **Direct (1:1) — ringing-модель**: `POST /calls` → у обоих ринг → accept (активный звонок) / reject / cancel (инициатором до accept). Пропущенный — system-сообщение в чате.
- **Групповые — join-модель** (как Telegram/Discord): `POST /calls` открывает комнату в группе (без ринга каждому), участники join/leave свободно; событиями `call.joined/left` виден живой состав. Рекомендуется закладывать сразу: SFU делает группу столь же дешёвой, как 1:1, схема БД одинакова.
- **Боты в звонках не участвуют** (нет аудио-тракта; `is_bot` при инициации/join — 422).
- Room name в LiveKit = `calls.id` (UUIDv7); жизнь комнаты управляется нашим lifecycle (ringing → active → ended), сироты в LiveKit не живут дольше TTL комнаты.

### Схема БД (§6): `calls`, `call_participants`

`calls`: `id` UUIDv7 PK (= room name), `chat_id`, `initiator_id`, `kind` enum(`audio`,`video`), `status` enum(`ringing`,`active`,`ended`), `created_at`, `started_at` (первый accept/join), `ended_at`. `call_participants`: PK (`call_id`,`user_id`), `joined_at`, `left_at` NULLABLE. Завершение: `active`-звонок без участников с `left_at IS NULL` → `ended`. «Пропущенный» у неответивших — дериват статуса и `call_participants` (отдельной таблицы нет).

### REST (§12) и WS-события (§9)

REST (все мутации — REST, WS — только уведомления; require_member на всё):
- `POST /calls` `{chat_id, kind}` → CallOut (direct → `ringing`; group → `ringing` + событие в группу)
- `POST /calls/{id}/accept|reject|cancel` — direct-флоу (accept → `active` + `started_at`; reject/cancel → `ended`)
- `POST /calls/{id}/join|leave` — group-флоу (и повторный вход при реконнекте); последний leave → `ended`. Leave в **direct**-звонке завершает звонок для обоих (1:1: сброс одним = конец звонка, как Telegram; решено 2026-11-13)
- `POST /calls/{id}/token` → `{token, ws_url}` — room-токен LiveKit (только участник чата И звонка; TTL ~10 мин, payload: room = call.id, identity = user.id, publish/subscribe)

WS-события (формат — `{call: <CallOut>}` либо `{call_id, user_id}` для joined/left): `call.ring`, `call.accepted`, `call.rejected`, `call.cancelled`, `call.joined`, `call.left`, `call.ended`. Ботам не доставляются (§10 — только `message.*`).

System-сообщения в ленте (§9, новые kinds в `SYSTEM_TEXTS`): `call_ended` («Звонок · 5:23» — payload: kind, duration_s, initiator_id), `call_missed` («Пропущенный звонок»). Пишутся при завершении звонка; цитировать/пересылать — запрещено (как всем system).

Cleanup-джоба (в существующий `periodic.py`): `ringing` старше 45 сек → `ended` (+ `call_missed`); `active` без участников → `ended` (+ `call_ended`, если ни одного system ещё нет).

### Room-токен — третье исключение из «бэкенд не выдаёт токены»

Аналогично presigned URL Silo (§8) и `mat_…` mini-apps (§11): скоупед JWT для внешней медиа-подсистемы — не аутентификация пользователя, а авторизация в конкретный ресурс (конкретная комната-звонок, TTL ~10 мин, только publish/subscribe). Подпись HS256 API-key/secret LiveKit'а; секрет — `APP_LIVEKIT_API_SECRET` в env (§13). Python server SDK LiveKit не нужен — обычный JWT.

### NAT/TURN

- Сервер с выделенным IP: `rtc.use_external_ip: true`; клиент за обычным NAT соединяется исходящим UDP к 50000–60000/udp — без TURN.
- Корпоративные сети с зарубленным UDP (20–40% реальных соединений): fallback через **coturn** — сначала UDP/TCP relay, конечный fallback — **TURN over TLS :443** (неотличим от HTTPS; требует DNS-имя turn.* и валидный сертификат). Связка «SFU с выделенным IP + TURN TLS» покрывает ~100% сетей.
- Порты LiveKit и конфиг — §13.

### UI (фронт)

- Кнопка 📞 (аудио) / 🎥 (видео, этап C) в шапке чата → `POST /calls`.
- Входящий: полноэкранный/плавающий оверлей ринга (звук, аватар, принять/отклонить) — по `call.ring`; живёт поверх роутинга (звонок не рвётся при навигации) — отдельный компонент у корня приложения, состояние — Zustand-стор (вне TanStack Query, как typing/presence).
- Активный звонок: панель с таймером, аватарами/составом, mute (локальный track.enabled), hang-up; групповой (этап B) — сетка участников из LiveKit-треков.
- Пропущенный/завершённый — system-сообщение в ленте чата.

### Этапы

- **A. Аудио 1:1**: compose (livekit + coturn), миграция `calls`/`call_participants`, сервис + REST + WS-события + system-сообщения + cleanup, ringing-UI direct, room-токен, TURN. Основной объём работ.
- **B. Групповые аудио** (+~25–30%): join-модель для group-чатов, живой состав в звонке, групповой UI. Схема и REST из A переиспользуются.
- **C. Видео**: публикация камеры + плитки (simulcast уже в SFU), шаринг экрана. Тот же контур, только UI.
