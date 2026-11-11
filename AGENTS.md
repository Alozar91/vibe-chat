# AGENTS.md — vibe-chat

Корпоративный мессенджер (self-hosted): личные/групповые чаты, боты с собственным API, файлы и фото, в перспективе mini-apps, звонки, мобильные приложения. Продуктовая и архитектурная правда — в `Docs/concept.md`; при противоречиях с этим файлом приоритет у концепции.

## Статус

Бэкенд MVP реализован (этапы 1–9 дорожной карты, 2026-11-11; 106 тестов): auth, чаты, сообщения+файлы, realtime, cleanup, боты, каркас mini-apps, реакции; персональные данные — в системе (Keycloak только для аутентификации, этап 9.1). Следующий этап — фронтенд (п.10). Реализационные решения (детали API, схема БД, структура пакетов) фиксируются в `Docs/concept.md` и здесь не дублируются.

## Стек (зафиксирован)

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy + Alembic, Pydantic v2
- **Frontend:** React + TypeScript + Vite (только web; мобильные — перспектива); UI — **Tailwind CSS + shadcn/ui**; data layer — **TanStack Query (REST-кэш) + Zustand (WS-состояние)**
- **CI:** нет — локальные проверки (ruff/mypy/pytest, oxlint/tsc/vitest); пересмотреть при появлении второй площадки разработки
- **DB:** PostgreSQL (основное хранилище всего)
- **Кэш/Pub/Sub:** Valkey — не Redis. Никогда не добавлять redis-пакеты/образы
- **Объектное хранилище:** Silo (S3-совместимый, форк MinIO от Pigsty) — не MinIO. В коде и конфигах именование Silo / `SILO_*`; только сам Silo-контейнер может использовать свои исторические `MINIO_*` env-переменные
- **Auth:** Keycloak (OIDC; MVP — логин-пароль, потом LDAP/Kerberos через федерацию). Realm-роли в MVP не используются; авторизация по членству в чатах; в realm-export обязателен audience mapper. Keycloak — **только идентификация/аутентификация** (`sub`); персональные данные (имя, фамилия, почта) — в PostgreSQL системы, из JWT-клеймов не берутся (§5 концепции)
- **Realtime:** WebSocket + Valkey Pub/Sub
- **Деплой:** Docker Compose, монорепо `backend/` + `frontend/` + `Docs/` + `deploy/`

## Ключевые архитектурные решения

- Бэкенд не выдаёт токены — только валидирует JWT Keycloak'а (JWKS, iss/aud/exp). Единственное исключение — скоупед opaque-токены `mat_…` для mini-apps (Docs/concept.md §11).
- Keycloak — только identification/authentication: из JWT берутся `sub` и `preferred_username` (начальный логин). Персональные данные (`first_name`, `last_name`, `email`, `display_name`, аватар, пояс) живут в PostgreSQL и редактируются через `PATCH /users/me`; из клеймов (`name`, `email` и т.п.) не берутся, с Keycloak не синхронизируются (Docs/concept.md §5).
- `messages.type` только `text|system`; тип медиа живёт исключительно в `attachments.kind` (сверяется с `real_mime_type`, несовпадение — 422). Не добавлять `image/video/file` в `messages.type`. Видео в MVP: метаданные извлекает клиент (ffmpeg на бэкенде нет).
- Файлы не проксируются через бэкенд: presigned PUT/GET напрямую в Silo; URL встраиваются в сериализацию сообщений. У Silo два адреса в конфиге: `SILO_INTERNAL_URL` (серверные операции) и `SILO_PUBLIC_URL` (host в presigned URL — он входит в подпись). Бэкенд генерирует thumbnails (Pillow), определяет реальный mime (не доверять клиенту); `thumb_key`/`blurhash` — в `files` (не в `attachments` — они генерируются до создания attachment'а); SVG — не image. Браузерный PUT в Silo — cross-origin: на Silo обязателен CORS, иначе загрузки падают на preflight.
- Боты: управляет только **платформенный админ** (`users.is_platform_admin`, MVP — seed-пользователь); в чаты ботов добавляют чат-админы; в Bot API есть чтение истории (`/bot/chats/{id}/messages`) — без него resync бота невозможен.
- `messages.id` — UUIDv7 (пагинация и сортировка по id), главный индекс `(chat_id, id)`; `updated_at` — курсор догоняния edit/delete при реконнекте (`?updated_after=`); идемпотентность отправки через `Idempotency-Key`/`client_ref` (UNIQUE sender+client_ref+chat_id). Все времена в БД/API — UTC (`timestamptz`, ISO 8601 `Z`); время сообщения передаёт только сервер.
- Часовые пояса: `messages.timezone` — эффективный пояс отправителя в момент отправки (клиент передаёт, сервер валидирует по IANA, иначе NULL; у ботов/system — NULL); режим отображения — `users.time_display` (`browser`|`as_sent`|`fixed`|`utc`).
- Сообщения удаляются soft delete; пересылка — только через `POST /messages/{id}/forward` (в обычной отправке forward-поля не принимаются), вложения при пересылке копируются, снапшот автора — в `forward_snapshot`; системные сообщения (`type=system`) нельзя цитировать/пересылать/редактировать. Чат удаляется soft delete (`chats.deleted_at`, в списках не показывается).
- Realtime: fanout через Valkey Pub/Sub; события ботов — Valkey Streams (long polling `/bot/updates`, offset = Stream ID, retention 24 ч, `resync: true` при отставании). Presence — счётчик соединений в Valkey (не в процессе бэкенда), `users.last_seen_at` пишется при обнулении счётчика.
- WS auth через одноразовые tickets (`/ws/ticket`, атомарное удаление GETDEL), не через токен в query. Истечение JWT в живом WS — норма, соединение не пере-валидируется. Client→server по WS — только `typing`; все мутации через REST. Несколько одновременных WS-соединений на пользователя допустимы (вкладки/устройства), каждое со своим ticket.
- Mini-apps: в MVP только каркас — поля в БД + два эндпоинта (one-time код → mat_-токен), контракт `postMessage` в концепции (§11). UI не строить.
- Реакции: только фиксированный набор эмодзи (`thumbs_up`, `heart`, `laugh`, `fire`, `check`), toggle-API `PUT /messages/{id}/reactions`, составной PK (message_id, user_id) — одна реакция на пользователя; не двигают `updated_at` сообщения (§6). Ботам реакции не доставляются (только message.*, §10).
- Масштаб MVP: до ~1k пользователей; вертикальные обновления, а не миграция на очереди/микросервисы.

## Документация

- `Docs/` — вся документация проекта, на русском языке.
- `Docs/concept.md` — общая концепция (стек, схема БД, API, realtime, боты, дорожная карта, открытые вопросы).
- Новые архитектурные решения сначала фиксируются в `Docs/`, потом код.
