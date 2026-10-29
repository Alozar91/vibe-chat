# Вайб.Chat — Архитектура системы

Версия: 1.0. Статус: утверждена к реализации.
Документ описывает итоговую архитектуру корпоративного мессенджера для **одной организации** после всех доработок. Исходный многотенантный план и ранний план v1 (`vibe-chat-backend-plan.md`) заменены этим документом.

---

## 1. Обзор

Корпоративный мессенджер для общения сотрудников внутри одной организации:

- web-клиент (React) и мобильные приложения iOS/Android (Flutter);
- вход по логину+паролю через **Keycloak** — единую точку входа (LDAP-федерация + локальные учётные записи, создаваемые администратором);
- личные и групповые чаты, упоминания, пересылка, ответы, редактирование/удаление;
- боты и интеграции (long polling, этап 2 — webhook'и);
- файлы и медиа, уведомления, поиск, администрирование, аудит.

Основной сценарий:

> Сотрудник входит по корпоративной учётной записи, автоматически получает доступ к чатам, общается, обменивается файлами, использует ботов и получает уведомления на всех устройствах.

---

## 2. Зафиксированные решения

| Компонент | Выбор |
|---|---|
| Бэкенд | Python 3.12, FastAPI, модульный монолит; два процесса: `api` (uvicorn, HTTP+WS) и `worker` (outbox-консьюмер, push, thumbnail'ы, AV, периодика) |
| Доступ к БД | SQLAlchemy 2 (async) + asyncpg, миграции Alembic, Pydantic v2 |
| API | REST + WebSocket (OpenAPI из FastAPI) |
| БД | PostgreSQL 16 |
| Кэш / pub/sub / сессии | **Valkey 8** (BSD-форк Redis, RESP-совместим; клиент `valkey-py`) |
| Файлы | S3-совместимое хранилище: MinIO (private bucket, presigned URL, SSE-S3). В dev-compose по умолчанию **SeaweedFS** (образы MinIO удалены с Docker Hub/quay без аутентификации); при наличии docker login можно вернуть `minio/minio` |
| Поиск | PostgreSQL FTS (`russian`) + pg_trgm; OpenSearch — при >5–10 млн сообщений |
| IdP | Keycloak **26.0** (один realm `messenger`; LDAP-федерация + локальные учётки). 26.3+ не использовать: runtime-protocol-mappers (audience/hardcoded claims) в 26.3.5 не применяются к токенам |
| Вход | Логин + пароль (телефон — только поле профиля, не вход) |
| Web | React + TypeScript (Vite), BFF-подход: HttpOnly cookie, серверные сессии в Valkey |
| Mobile | Flutter: OIDC Authorization Code + PKCE, `flutter_appauth`, `flutter_secure_storage` |
| Push | FCM (Android), APNs (iOS), Web Push (VAPID), in-app |
| Очереди | Нет отдельного брокера: Postgres outbox + Valkey Pub/Sub; Kafka — при росте |
| Развёртывание | Docker Compose, один сервер, TLS на nginx; горизонтальное масштабирование `--scale api=N` |
| Масштаб | 500–5000 сотрудников |
| Мониторинг | Prometheus + Grafana + Loki (опциональный compose-профиль) |

Ключевые принципы:

1. Бэкенд никогда не видит и не хранит пароли — только Keycloak.
2. Одна организация, без тенантности: глобальные роли на `users.role`, настройки организации в `app_settings`.
3. Сообщения — лента чата с ключом `(chat_id, seq)`; персональные копии не создаются.
4. Прочитанность — `chat_members.last_read_seq`.
5. Доставка событий: достоверный путь — outbox в Postgres; быстрый путь — Valkey Pub/Sub.
6. Бизнес-авторизация (чаты, роли, права) — в БД мессенджера; аутентификация — в Keycloak.
7. Аудит — append-only, не изменяется задним числом.
8. Большие группы: без копий сообщений, пагинация, асинхронные уведомления, батчи.

---

## 3. Высокоуровневая схема

```text
[Web React SPA + Admin UI]   [Flutter iOS/Android]      [Бот-интеграция (1C/Jira/CI)]
  BFF: HttpOnly cookie          OIDC PKCE (системный       Bearer bot-token,
  (сессия в Valkey)             браузер), Bearer           long polling getUpdates
        │                             │                          │
        └───────────────┬─────────────┴──────────────────────────┘
                        ▼
        ┌─────────────────── nginx (TLS, /ws upgrade, rate-limit L7) ───────────────────┐
                        │                                     │
                        ▼                                     ▼
        ┌──────────────────────────────────┐   ┌──────────────────────────────────┐
        │  FastAPI api ×N                  │   │  FastAPI worker                  │
        │  REST, WebSocket, admin          │   │  outbox-консьюмер: push, бейджи, │
        │  (горизонтально: --scale api=N)  │   │  thumbnail'ы, AV, периодика      │
        └───────┬──────────┬─────────┬─────┘   └────────────────┬─────────────────┘
                │          │         │                          │
     ┌──────────▼───┐ ┌────▼─────┐ ┌─▼────────┐  ┌──────────────▼───────────┐
     │ PostgreSQL 16│ │ Valkey 8 │ │ S3-хранилище│  │ Keycloak 26.0           │
     │ данные, FTS, │ │ сессии,  │ │ файлы    │  │ realm messenger:         │
     │ outbox, аудит│ │ pub/sub, │ │ private  │  │ LDAP-федерация, OIDC,    │
     │              │ │ presence,│ │ bucket   │  │ Admin API, MFA (опция)   │
     │              │ │ rate-lim │ │          │  │                          │
     └──────────────┘ └──────────┘ └──────────┘  └──────────────────────────┘
```

---

## 4. Развёртывание (Docker Compose)

```text
nginx (TLS, /ws upgrade, rate-limit L7, статика веб-клиента)
  ├─ api         (uvicorn, 2–4 воркера; docker compose up --scale api=2)
  ├─ worker      (outbox → Valkey pub/sub, push FCM/APNs/WebPush, периодика)
  ├─ postgres 16
  ├─ valkey 8    (сессии, pub/sub, presence, rate-limit, кэш)
  ├─ minio       (S3-совместимое хранилище; dev: SeaweedFS, prod: MinIO), порт S3 9000
  ├─ keycloak 26.0 (realm messenger, LDAP-федерация)
  └─ [profile monitoring] prometheus + grafana + loki
  └─ [profile av] clamav (скан вложений в worker)
```

- Конфигурация — `.env` + pydantic-settings; секреты — docker secrets / переменные окружения (Vault — позже).
- **Bootstrap-админ**: при первом деплое CLI-команда `python -m app.cli bootstrap-admin` повышает пользователя из ENV `BOOTSTRAP_ADMIN_USERNAME` (вошедшего через LDAP или созданного локально) до `role='owner'`.
- Бэкапы: nightly `pg_dump` + WAL-архив (WAL-G), `mc mirror` bucket'а MinIO, экспорт realm Keycloak; тест восстановления — ежеквартально. Valkey — ephemeral, в бэкапы не входит.
- Миграции: `alembic upgrade head` при каждом деплое, только вперёд; бэкап перед миграцией обязателен.
- CI: ruff, mypy, pytest (testcontainers: pg, valkey, keycloak, minio), сборка образов; deploy — `compose pull && alembic upgrade head && compose up -d`.
- Valkey вместо Redis: BSD-лицензия, RESP-совместимость — код и команды без изменений.

---

## 5. Аутентификация и авторизация

### 5.1. Realm `messenger`

- **User Federation: LDAP/AD** (read-only): import users, периодический sync (каждый час) + sync on demand; маппер групп → claim `groups` в токене.
- **Локальные учётки**: создаёт админ через админ-панель → бэкенд вызывает **Keycloak Admin API** (клиент `messenger-backend`, service account): создать пользователя, задать временный пароль, `requiredActions=[UPDATE_PASSWORD]`; при наличии SMTP — `execute-actions-email` (письмо со ссылкой установки пароля).
- Политики: password policy, brute-force detection, опциональный TOTP (Optional Action) — MFA включается флагом realm без изменения кода.
- События Keycloak (login success/fail): периодический забор через Admin API → таблица `login_events` (или webhook — этап 2).

### 5.2. Клиенты Keycloak

| Client | Тип | Назначение |
|---|---|---|
| `messenger-web` | confidential, standard flow | BFF: обмен кода на токены на бэкенде |
| `messenger-mobile` | public, PKCE required | Flutter, системный браузер (AppAuth) |
| `messenger-api` | bearer-only / audience | audience в access-токене |
| `messenger-backend` | confidential, service account | Keycloak Admin API, служебные вызовы |

### 5.3. Вход Web (BFF)

```text
1. GET /v1/auth/login → 302 на Keycloak authorize
2. Пользователь входит по логину+паролю (LDAP или локальная учётка)
3. GET /v1/auth/callback (code) → бэкенд обменивает код на токены
4. Проверка id_token (authlib, JWKS) → JIT-создание/обновление пользователя
5. Серверная сессия в Valkey (TTL 12ч, скользящее продление, refresh-ротация на бэкенде)
6. Клиент получает HttpOnly + Secure + SameSite=Lax cookie + CSRF-токен для мутаций
```

- `POST /v1/auth/logout` — revoke refresh-токена в Keycloak + удаление сессии; `POST /v1/auth/logout-all` — все сессии.
- `GET /v1/auth/sessions`, `DELETE /v1/auth/sessions/{id}` — список/отзыв.
- Смена пароля — только через Keycloak (`/realms/messenger/account` или сброс админом).

### 5.4. Вход Mobile (Flutter)

Authorization Code + PKCE через системный браузер; токены в `flutter_secure_storage` (iOS Keychain / Android Keystore); access-токен 5 мин, refresh с ротацией; `Authorization: Bearer` для API и WS.

Запрещено: WebView для входа, implicit flow, password grant, хранение токенов в открытом виде.

### 5.5. Проверка доступа на бэкенде (единая для web/mobile/bot)

```text
1. Извлечь токен (cookie-сессия → внутренний user_id; Bearer → JWT; bot → sha256-хэш)
2. JWT: подпись по JWKS (кэш, kid), iss, aud=messenger-api, exp
3. Найти users по keycloak_sub; проверить status='active' (кэш в Valkey 30 c)
4. Бизнес-права: членство в чате / роль в чате / роль в организации — из БД (кэш 30–60 c)
```

**Отключение сотрудника**: админ → `POST /v1/admin/users/{id}/disable` → статус в БД + disable в Keycloak + revoke сессий + периодическая перепроверка закрывает живые WS. Эффект ≤ 30 c даже для уже выданных токенов. Данные и чаты сохраняются.

### 5.6. Жизненный цикл пользователей

- **JIT**: при первом входе создаётся `users` по claims (sub, preferred_username, name, email, groups).
- **Синк**: ежечасная задача worker'а сверяет активных пользователей Keycloak ↔ `users` (disable/enable, профиль).
- **Создание админом**: панель → Keycloak Admin API (временный пароль или письмо); массово — CSV-импорт (`POST /v1/admin/users/import`).
- **Сброс пароля**: админ (`POST /v1/admin/users/{id}/reset-password`) — temp password или письмо; при недоступном SMTP — fallback на временный пароль.
- **Bootstrap-админ**: CLI по ENV (см. раздел 4).
- `users.source`: `ldap` | `local` | `bot`. Профиль LDAP-пользователя редактируется только синком, локального — админом и самим пользователем.

### 5.7. Роли и права

Роли организации (глобально, на пользователе): `owner` — полный контроль; `admin` — администрирование пользователей, чатов, ботов, политик; `member` — обычный участник.

Роли в чате: `owner` (владелец чата), `admin` (администратор чата), `member`.

Матрица прав в чате:

| Действие | Владелец чата | Админ чата | Участник |
|---|---:|---:|---:|
| писать сообщения | да | да | да |
| редактировать свои сообщения | да | да | да |
| удалять свои сообщения | да | да | да |
| удалять чужие сообщения | да | да | нет |
| добавлять участников | да | да | зависит от настроек чата |
| удалять участников | да | да | нет |
| закреплять сообщения | да | да | нет |
| приглашения-ссылки (создать/отозвать) | да | да | нет |
| добавлять/удалять ботов | да | да | нет |
| изменять настройки чата | да | да | нет |
| удалять чат | да | нет | нет |

Жизненный цикл ботов: создание, токены, удаление — `owner`/`admin` организации; добавление/удаление бота в группу — владелец/админ чата; DM с ботом разрешён любому пользователю.

Проверка прав выполняется на каждом запросе: роль организации → членство в чате → роль в чате → владелец объекта. Данные клиента без проверки не доверяются.

---

## 6. Модель данных (PostgreSQL)

### 6.1. Принципы

1. Пользователь хранится локально; связь с IdP — `users.keycloak_sub` (subject из токена).
2. Чаты без `org_id` (одна организация); direct-чаты дедуплицируются уникальной парой.
3. Ключ сообщения — `chat_id + seq`; seq монотонный внутри чата.
4. Участники хранят `last_read_seq`; копий сообщений на участника нет.
5. Файлы независимы от сообщений (`files`), к сообщению привязываются через `message_attachments`; аватары — `users.avatar_file_id`.
6. Достоверные события — outbox; аудит append-only.

### 6.2. Схема

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TYPE user_kind AS ENUM ('human', 'bot');
CREATE TYPE user_role AS ENUM ('owner', 'admin', 'member');
CREATE TYPE user_status AS ENUM ('active', 'disabled');

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind user_kind NOT NULL DEFAULT 'human',
  keycloak_sub text UNIQUE,                -- NULL для ботов
  username text NOT NULL UNIQUE,           -- логин (preferred_username)
  full_name text NOT NULL,
  email text UNIQUE,
  phone text,                              -- только контакт, не вход
  title text,
  role user_role NOT NULL DEFAULT 'member',
  status user_status NOT NULL DEFAULT 'active',
  source text NOT NULL DEFAULT 'local',    -- ldap | local | bot
  notification_settings jsonb NOT NULL DEFAULT '{}', -- dnd_until, режим по умолчанию
  is_deleted boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX users_full_name_trgm_idx ON users USING gin (full_name gin_trgm_ops);

CREATE TABLE app_settings (               -- единственная строка
  id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  org_name text NOT NULL,
  settings jsonb NOT NULL DEFAULT '{}'    -- лимиты файлов, порог @all и т.п.
);

CREATE TABLE devices (                    -- push-токены
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  platform text NOT NULL,                  -- ios | android | web
  push_token text,                         -- FCM/APNs token
  webpush_endpoint text,
  webpush_keys jsonb,
  device_id text,
  app_version text,
  last_seen_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX devices_push_token_uq ON devices (platform, push_token) WHERE push_token IS NOT NULL;
CREATE UNIQUE INDEX devices_webpush_uq ON devices (webpush_endpoint) WHERE webpush_endpoint IS NOT NULL;
CREATE INDEX devices_user_idx ON devices (user_id);

CREATE TYPE chat_type AS ENUM ('direct', 'group');
CREATE TYPE chat_member_role AS ENUM ('owner', 'admin', 'member');
CREATE TYPE chat_member_status AS ENUM ('invited', 'active', 'left', 'removed', 'banned');

CREATE TABLE chats (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  type chat_type NOT NULL,
  title text,
  avatar_url text,
  description text,
  created_by uuid REFERENCES users(id),
  is_public boolean NOT NULL DEFAULT false,
  members_count integer NOT NULL DEFAULT 0,
  last_message_seq bigint NOT NULL DEFAULT 0,
  last_message_at timestamptz,
  settings jsonb NOT NULL DEFAULT '{}',    -- who_can_add_members, @all_allowed и т.п.
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);
CREATE INDEX chats_last_message_idx ON chats (last_message_at DESC);

CREATE TABLE direct_chats (
  chat_id uuid PRIMARY KEY REFERENCES chats(id) ON DELETE CASCADE,
  user_a uuid NOT NULL REFERENCES users(id),
  user_b uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (user_a <> user_b)
);
CREATE UNIQUE INDEX direct_chats_pair_uq
  ON direct_chats (least(user_a, user_b), greatest(user_a, user_b));

CREATE TABLE chat_members (
  chat_id uuid NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role chat_member_role NOT NULL DEFAULT 'member',
  status chat_member_status NOT NULL DEFAULT 'active',
  notifications text NOT NULL DEFAULT 'all',   -- all | mentions | none
  muted_until timestamptz,
  last_read_seq bigint NOT NULL DEFAULT 0,
  last_read_at timestamptz,
  invited_by uuid REFERENCES users(id),
  joined_at timestamptz NOT NULL DEFAULT now(),
  left_at timestamptz,
  PRIMARY KEY (chat_id, user_id)
);
CREATE INDEX chat_members_user_idx ON chat_members (user_id, status);
CREATE INDEX chat_members_chat_idx ON chat_members (chat_id, status);

CREATE TABLE chat_invites (               -- invite-ссылки в группы
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  chat_id uuid NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  code text NOT NULL UNIQUE,               -- 128-битный случайный токен
  created_by uuid NOT NULL REFERENCES users(id),
  domain_limit text,                       -- NULL = любой активный пользователь
  expires_at timestamptz,
  max_uses integer,                        -- NULL = без лимита
  uses integer NOT NULL DEFAULT 0,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX chat_invites_chat_idx ON chat_invites (chat_id);

CREATE TYPE message_type AS ENUM ('text', 'image', 'file', 'audio', 'video', 'card', 'system');

CREATE TABLE messages (
  chat_id uuid NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  seq bigint NOT NULL,
  sender_id uuid NOT NULL REFERENCES users(id),
  type message_type NOT NULL DEFAULT 'text',
  body text NOT NULL DEFAULT '',
  data jsonb NOT NULL DEFAULT '{}',        -- forwarded_from, метаданные карточек и т.п.
  reply_to_seq bigint,
  client_idempotency_key text,
  search_vector tsvector GENERATED ALWAYS AS (to_tsvector('russian', body)) STORED,
  edited_at timestamptz,
  deleted_at timestamptz,                  -- tombstone, body затирается
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (chat_id, seq)
);
CREATE UNIQUE INDEX messages_idempotency_uq
  ON messages (chat_id, sender_id, client_idempotency_key) WHERE client_idempotency_key IS NOT NULL;
CREATE INDEX messages_page_idx ON messages (chat_id, seq DESC);
CREATE INDEX messages_fts_idx ON messages USING gin (search_vector);
CREATE INDEX messages_created_idx ON messages (created_at DESC);

CREATE TABLE files (                      -- файлы, независимые от сообщений
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL REFERENCES users(id),
  name text NOT NULL,
  mime_type text NOT NULL,
  size_bytes bigint NOT NULL,
  sha256 text NOT NULL,
  storage_key text NOT NULL,               -- ключ объекта в MinIO
  thumbnail_key text,
  width integer, height integer, duration_ms integer,
  av_status text NOT NULL DEFAULT 'skip',  -- pending | clean | infected | skip
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX files_owner_idx ON files (owner_id);

CREATE TABLE message_attachments (
  chat_id uuid NOT NULL,
  message_seq bigint NOT NULL,
  file_id uuid NOT NULL REFERENCES files(id),
  position smallint NOT NULL DEFAULT 0,
  PRIMARY KEY (chat_id, message_seq, file_id),
  CONSTRAINT message_attachments_message_fk FOREIGN KEY (chat_id, message_seq)
    REFERENCES messages(chat_id, seq) ON DELETE CASCADE
);
CREATE INDEX message_attachments_file_idx ON message_attachments (file_id);

ALTER TABLE users ADD COLUMN avatar_file_id uuid REFERENCES files(id);

CREATE TABLE message_mentions (
  chat_id uuid NOT NULL, message_seq bigint NOT NULL,
  mentioned_user_id uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (chat_id, message_seq, mentioned_user_id),
  CONSTRAINT message_mentions_fk FOREIGN KEY (chat_id, message_seq)
    REFERENCES messages(chat_id, seq) ON DELETE CASCADE
);
CREATE INDEX message_mentions_user_idx ON message_mentions (mentioned_user_id, chat_id);

CREATE TABLE message_reactions (
  chat_id uuid NOT NULL, message_seq bigint NOT NULL,
  user_id uuid NOT NULL REFERENCES users(id), emoji text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (chat_id, message_seq, user_id, emoji),
  CONSTRAINT message_reactions_fk FOREIGN KEY (chat_id, message_seq)
    REFERENCES messages(chat_id, seq) ON DELETE CASCADE
);

CREATE TABLE bots (
  user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  description text,
  webhook_url text,                        -- используется с этапа 2
  webhook_secret_ref text,                 -- используется с этапа 2
  is_enabled boolean NOT NULL DEFAULT true,
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bot_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bot_id uuid NOT NULL REFERENCES bots(user_id) ON DELETE CASCADE,
  name text NOT NULL,
  token_hash text NOT NULL UNIQUE,         -- sha256; токен в открытом виде показывается один раз
  token_prefix text NOT NULL,
  scopes text[] NOT NULL DEFAULT '{}',     -- применяются с этапа 2
  expires_at timestamptz, revoked_at timestamptz, last_used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bot_subscriptions (           -- ЭТАП 2 (webhook-доставка); в MVP боты получают события long polling'ом
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bot_id uuid NOT NULL REFERENCES bots(user_id) ON DELETE CASCADE,
  event_type text NOT NULL,
  chat_id uuid REFERENCES chats(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX bot_subscriptions_uq ON bot_subscriptions
  (bot_id, event_type, COALESCE(chat_id, '00000000-0000-0000-0000-000000000000'::uuid));

CREATE TABLE bot_commands (
  bot_id uuid NOT NULL REFERENCES bots(user_id) ON DELETE CASCADE,
  command text NOT NULL, description text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (bot_id, command)
);

CREATE TABLE outbox_events (
  seq bigserial PRIMARY KEY,               -- монотонный курсор, в т.ч. для long polling ботов
  aggregate_type text NOT NULL, aggregate_id text NOT NULL,
  event_type text NOT NULL,
  chat_id uuid,                            -- для фильтрации событий ботов
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), published_at timestamptz
);
CREATE INDEX outbox_unpublished_idx ON outbox_events (created_at) WHERE published_at IS NULL;
CREATE INDEX outbox_chat_seq_idx ON outbox_events (chat_id, seq);

CREATE TABLE login_events (
  id bigserial PRIMARY KEY,
  user_id uuid REFERENCES users(id), origin text,   -- password | ldap
  status text NOT NULL, ip inet, user_agent text, error_code text,
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX login_events_user_idx ON login_events (user_id, created_at DESC);

CREATE TABLE audit_logs (
  id bigserial PRIMARY KEY,
  actor_id uuid REFERENCES users(id),
  action text NOT NULL, entity_type text, entity_id text,
  metadata jsonb NOT NULL DEFAULT '{}', ip inet,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_logs_time_idx ON audit_logs (created_at DESC);
CREATE INDEX audit_logs_entity_idx ON audit_logs (entity_type, entity_id);
```

### 6.3. Ключевые механики

- **seq**: в транзакции отправки `UPDATE chats SET last_message_seq = last_message_seq + 1 WHERE id = $1 RETURNING last_message_seq` — блокировка строки чата сериализует нумерацию.
- **Идемпотентность**: клиент шлёт заголовок `Idempotency-Key`; уникальный индекс `(chat_id, sender_id, client_idempotency_key)`; повтор возвращает существующее сообщение без дубля.
- **Прочитанность/бейджи**: непрочитано в чате = `chats.last_message_seq − chat_members.last_read_seq`; суммарный бейдж — кэш в Valkey, инвалидация при чтении/новом сообщении.
- **Пересылка (этап 1)**: `POST /messages` с `forward: [{chat_id, seq}, …]` создаёт копии с `data.forwarded_from` (исходный чат, seq, автор, время); вложения переиспользуют `file_id` без копирования объектов; отправитель должен быть участником исходного чата.
- **Outbox как журнал ботов**: бот читает `outbox_events WHERE seq > cursor` (long polling); published-события удаляются retention'ом (7 дней) — отставший за границу бот делает resync с текущего события.
- **Invite-ссылки**: join только активному пользователю; проверка кода/срока/лимита/отзыва, инкремент `uses` атомарно.
- **Direct-чат**: уникальная пара `(least, greatest)` не даёт дублей.
- **Партиционирование `messages`**: не делать сейчас; при >50–100 млн строк — по `hash(chat_id)` или `created_at`.

---

## 7. Структура бэкенда

```text
backend/
  pyproject.toml            # ruff, mypy, pytest
  alembic/                  # миграции
  app/
    main.py                 # сборка FastAPI
    config.py               # pydantic-settings
    cli.py                  # python -m app.cli bootstrap-admin (ENV BOOTSTRAP_ADMIN_USERNAME)
    db/                     # engine (asyncpg), пул, session factory + get_session (UoW), base
    core/                   # security (JWT/JWKS), permissions, rate-limit, errors, pagination
    modules/
      auth/                 # OIDC BFF-флоу, Valkey-сессии, Keycloak Admin API клиент
      users/                # профиль, поиск пользователей
      chats/                # чаты, участники, роли, direct, invites
      messages/             # отправка (seq+идемпотентность+outbox), история, reply, mentions, пересылка
      media/                # upload-intents, presigned, лимиты, avatars
      realtime/             # WS endpoint, Valkey pub/sub, typing, presence
      notifications/        # правила, FCM/APNs/WebPush, батчинг, бейджи
      bots/                 # CRUD, токены, long polling getUpdates, команды
      search/               # FTS + trgm
      admin/                # пользователи, disable, аудит, сессии, статистика
      audit/                # запись и чтение аудит-логов
  worker/
    consumer.py             # outbox → Valkey pub/sub, push (bot webhooks — с этапа 2, retry/backoff)
    jobs.py                 # периодика: Keycloak↔users sync, av-скан, cleanup, thumbnail'ы, retention
tests/
deploy/                     # docker-compose.yml, keycloak/realm-export.json, nginx/
web/                        # React + TypeScript (Vite), маршруты /admin — админ-панель
mobile/                     # Flutter
```

Зависимости: `fastapi`, `uvicorn[standard]` (uvloop), `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `valkey` (valkey-py), `authlib`, `pyjwt[crypto]`, `httpx`, `boto3` (MinIO), `pillow` (thumbnail'ы), `pywebpush`, `aioapns`, `firebase-admin` (или HTTP v1 API), `prometheus-fastapi-instrumentator`. Очередь задач — собственный outbox-консьюмер (asyncio) в `worker`; Celery/ARQ не нужны.

Клиентские SDK: TS-клиент (web) и Dart-клиент (mobile) генерируются из OpenAPI-схемы FastAPI (openapi-typescript, openapi-generator).

Практика Python: все I/O — async; CPU-работа (thumbnail'ы, AV) — только в worker; WS-авторизация stateless (токен при handshake) → масштабирование `--scale api=N` без sticky-сессий.

**Работа с БД (session как unit of work)**: один `AsyncSession` на обработку запроса — dependency `get_session`; репозитории и сервисы получают сессию параметром и не создают её сами, поэтому все операции запроса идут через один объект. Граница транзакции — запрос: commit в teardown зависимости, rollback при исключении (или `async with session.begin()`). Именно так обеспечивается атомарность отправки сообщения: `UPDATE chats (seq)` + INSERT messages/attachments/mentions + INSERT outbox — одна транзакция. Внешние вызовы (Keycloak Admin API, push, presigned URL) — за пределами транзакций, чтобы не держать блокировки БД. В WebSocket и worker'е — UoW на операцию, а не на соединение: живое WS-соединение сессию не держит (иначе исчерпается пул), каждое обрабатываемое событие/задание открывает свою короткую сессию. Пул asyncpg: 10–20 соединений на инстанс api, отдельный пул у worker.

---

## 8. API (v1)

```text
# Аутентификация/сессии (BFF)
GET    /v1/auth/login | /v1/auth/callback
POST   /v1/auth/logout | /v1/auth/logout-all
GET    /v1/auth/sessions          DELETE /v1/auth/sessions/{session_id}

# Пользователи
GET    /v1/me   PATCH /v1/me      # вкл. notification_settings, phone, avatar_file_id
GET    /v1/users/{user_id}   GET  /v1/users/search

# Настройки организации (одна; чтение — все, изменение — owner/admin)
GET    /v1/settings               PATCH /v1/settings

# Чаты
GET    /v1/chats   POST /v1/chats   # dm по user_id | group
GET    /v1/chats/{chat_id}   PATCH /v1/chats/{chat_id}   DELETE /v1/chats/{chat_id}
POST   /v1/chats/{chat_id}/members   DELETE /v1/chats/{chat_id}/members/{user_id}
POST   /v1/chats/{chat_id}/leave     POST /v1/chats/{chat_id}/read
GET    /v1/chats/{chat_id}/members
PATCH  /v1/chats/{chat_id}/members/me   # notifications: all|mentions|none, muted_until

# Сообщения
POST   /v1/chats/{chat_id}/messages   # body + attachments(file_id) + reply_to_seq + forward + Idempotency-Key
GET    /v1/chats/{chat_id}/messages   # пагинация по seq
GET    /v1/chats/{chat_id}/messages/{seq}
PATCH  /v1/chats/{chat_id}/messages/{seq}
DELETE /v1/chats/{chat_id}/messages/{seq}
POST   /v1/chats/{chat_id}/messages/{seq}/reactions
DELETE /v1/chats/{chat_id}/messages/{seq}/reactions

# Устройства и уведомления
POST   /v1/devices                DELETE /v1/devices/{device_id}

# Приглашения в группы (ссылки)
POST   /v1/chats/{chat_id}/invites       GET /v1/chats/{chat_id}/invites
DELETE /v1/chats/{chat_id}/invites/{invite_id}
POST   /v1/invites/{code}/join           # код, срок, лимит, отзыв; активный пользователь

# Файлы
POST   /v1/media/upload-intents → {file_id, presigned PUT, ttl 15m, лимиты}
POST   /v1/media/upload-complete → HEAD-проверка объекта, статус ready (preview владельцу)
GET    /v1/media/{file_id}/url → presigned GET 5m (владелец | членство в чате | аватар)

# Боты (Bearer bot-token; long polling)
POST   /v1/bots   GET /v1/bots   GET/PATCH/DELETE /v1/bots/{bot_id}
POST   /v1/bots/{bot_id}/tokens          DELETE /v1/bots/{bot_id}/tokens/{token_id}
POST   /v1/bots/{bot_id}/commands
GET    /v1/bots/me                       GET /v1/bots/getUpdates?timeout=30&offset=
# webhook-доставка, подписки, scopes — этап 2

# Поиск
GET    /v1/search?q=&type=messages|chats|users&chat_id=&author_id=&date_from=&date_to=

# Админка (role='owner'|'admin')
GET    /v1/admin/users
POST   /v1/admin/users                            # создание → Keycloak Admin API
POST   /v1/admin/users/import                     # CSV-импорт
POST   /v1/admin/users/{user_id}/reset-password   # temp password или письмо
POST   /v1/admin/users/{user_id}/disable|enable   # БД + Keycloak + revoke сессий
GET    /v1/admin/sessions?user_id=                DELETE /v1/admin/sessions/{id}
GET    /v1/admin/stats                            # DAU, сообщения/день, объём хранилища
GET    /v1/admin/audit
GET    /v1/admin/bots                POST /v1/admin/bots/{bot_id}/disable
```

### 8.1. Соглашения

- Аутентификация: web — cookie-сессия + `X-CSRF-Token` в заголовке мутаций; mobile/bot — `Authorization: Bearer <token>`.
- `Idempotency-Key: <uuid>` — обязателен для `POST /messages`; повтор с тем же ключом возвращает исходное сообщение без дубля (200 вместо 201).
- Пагинация: `?limit=` (по умолчанию 50, максимум 100) + курсоры: сообщения — `before_seq`/`after_seq`, списки — `offset`; в ответе `next_offset` / `has_more`.
- Идентификаторы — UUID, время — ISO 8601 UTC.
- Ошибки — единый формат, HTTP-статус соответствует:

```json
{ "error": { "code": "chat_member_required", "message": "Вы не участник чата", "details": {} } }
```

Основные коды: `400 validation_error`, `401 unauthorized`, `403 forbidden` / `chat_member_required`, `404 not_found`, `409 duplicate_chat`, `413 file_too_large`, `429 rate_limited` (+ `Retry-After`), `503 degraded`.

### 8.2. Структуры запросов и ответов

Канонические структуры `User`, `Chat`, `Message` используются во всех эндпоинтах и в WS-событиях (раздел 9).

**Пользователи**

`GET /v1/me` →

```json
{
  "id": "3f1a…", "kind": "human", "username": "ivanov",
  "full_name": "Иван Иванов", "email": "ivanov@corp.ru",
  "phone": "+7 900 000-00-00", "title": "Backend-разработчик",
  "avatar_url": "/v1/media/9f2c…/url",
  "role": "member", "status": "active", "source": "ldap",
  "notification_settings": { "default_mode": "all", "dnd_until": null },
  "created_at": "2026-01-10T09:00:00Z"
}
```

`PATCH /v1/me` ← `{ "full_name": "…", "phone": "…", "title": "…", "avatar_file_id": "uuid", "notification_settings": { "default_mode": "mentions", "dnd_until": "2026-10-28T18:00:00Z" } }` → `User`. Для `source=ldap` редактируемые поля ограничены.

`GET /v1/users/search?q=иван&limit=20` → `{ "items": [ { "id": "…", "username": "ivanov", "full_name": "Иван Иванов", "title": "…", "avatar_url": null, "status": "active" } ], "next_offset": 20 }`

**Настройки организации**

`GET /v1/settings` →

```json
{
  "org_name": "Вайб",
  "settings": {
    "message_max_length": 4096,
    "max_file_size_mb": 100,
    "max_attachments": 10,
    "max_group_members": 10000,
    "all_mention_threshold": 100
  }
}
```

`PATCH /v1/settings` — то же тело, только `owner`/`admin`.

**Чаты**

`POST /v1/chats` ←

```json
{ "type": "group", "title": "Проект X", "description": "…", "member_ids": ["uuid1", "uuid2"] }
```

Для direct: `{ "type": "direct", "user_id": "uuid" }` — повторный вызов с той же парой возвращает существующий чат (без дубля).

→ `Chat`:

```json
{
  "id": "…", "type": "group", "title": "Проект X", "description": null,
  "avatar_url": null, "created_by": "…",
  "members_count": 3, "last_message_seq": 0, "last_message_at": null,
  "settings": { "who_can_add_members": "admins", "all_allowed": true },
  "my_role": "owner", "unread": 0, "muted_until": null,
  "created_at": "…", "updated_at": "…"
}
```

`GET /v1/chats?limit=50` → `{ "items": [Chat], "next_offset": 50 }` — сортировка по `last_message_at DESC`.

Члены чата:

- `POST /v1/chats/{id}/members` ← `{ "user_ids": ["uuid"], "role": "member" }` → `{ "added": ["uuid"], "skipped": [] }`; каждому добавленному — системное сообщение в ленте + WS `chat.member.joined`.
- `GET /v1/chats/{id}/members?limit=50` → `{ "items": [ { "user": User, "role": "admin", "status": "active", "last_read_seq": 118, "joined_at": "…" } ], "next_offset": 50 }`
- `PATCH /v1/chats/{id}/members/me` ← `{ "notifications": "mentions", "muted_until": "…" }` → объект членства.
- `POST /v1/chats/{id}/read` ← `{ "last_read_seq": 121 }` → `{ "unread": 0 }`.
- `POST /v1/chats/{id}/leave` → 204. `DELETE /v1/chats/{id}/members/{user_id}` → 204 (+ WS `chat.member.left`). `DELETE /v1/chats/{id}` → 204 (только владелец, soft delete).

**Сообщения**

`POST /v1/chats/{id}/messages` (заголовок `Idempotency-Key`) ←

```json
{
  "body": "Отчёт готов, @ivanov посмотрите",
  "attachments": ["9f2c…"],
  "reply_to_seq": 118,
  "forward": [{ "chat_id": "…", "seq": 42 }]
}
```

→ 201 `Message`:

```json
{
  "chat_id": "…", "seq": 121, "sender_id": "…",
  "type": "text",
  "body": "Отчёт готов, @ivanov посмотрите",
  "data": { "forwarded_from": [{ "chat_id": "…", "seq": 42, "sender_id": "…", "sent_at": "…" }] },
  "reply_to_seq": 118,
  "mentions": [{ "user_id": "…", "username": "ivanov" }],
  "mentions_all": false,
  "attachments": [{
    "file_id": "9f2c…", "name": "report.pdf", "mime_type": "application/pdf",
    "size_bytes": 1048576, "width": null, "height": null,
    "thumbnail_url": null, "url": "/v1/media/9f2c…/url"
  }],
  "reactions": {},
  "edited_at": null, "deleted_at": null, "created_at": "…"
}
```

- `body` — markdown, упоминания `@username` и `@all` (парсит сервер, `mentions`/`mentions_all` — результат парсинга).
- `reactions` — агрегированные счётчики (этап 2): `{ "👍": { "count": 3, "my": true } }`.
- Повтор с тем же `Idempotency-Key` → 200, та же запись.

`GET /v1/chats/{id}/messages?limit=50&before_seq=121` → `{ "items": [Message], "has_more": true, "next_before_seq": 71 }`; `after_seq` — для resync после переподключения. `PATCH …/{seq}` ← `{ "body": "…" }` → `Message` (`edited_at`); `DELETE …/{seq}` → 204 (tombstone, WS `message.deleted`). Реакции (этап 2): `POST /messages/{seq}/reactions` ← `{ "emoji": "👍" }` → `{ "count": 3 }`; `DELETE` → 204.

**Устройства**

`POST /v1/devices` ← `{ "platform": "android", "push_token": "fcm-token…", "device_id": "…", "app_version": "1.0.0" }` либо `{ "platform": "web", "webpush_subscription": { "endpoint": "https://…", "keys": { "p256dh": "…", "auth": "…" } } }` → `{ "id": "uuid" }`; `DELETE /v1/devices/{id}` → 204.

**Приглашения**

`POST /v1/chats/{id}/invites` ← `{ "expires_at": "2026-11-01T00:00:00Z", "max_uses": 10, "domain_limit": null }` →

```json
{
  "id": "…", "chat_id": "…", "code": "8f3a…",
  "url": "https://chat.corp/join/8f3a…",
  "uses": 0, "max_uses": 10,
  "expires_at": "…", "revoked_at": null
}
```

`POST /v1/invites/{code}/join` → `Chat` (пользователь становится участником); ошибки: 404 — код не найден, 410 — истёк/отозван, 429 — лимит исчерпан. `DELETE /v1/chats/{id}/invites/{invite_id}` → 204.

**Файлы**

`POST /v1/media/upload-intents` ← `{ "name": "report.pdf", "mime_type": "application/pdf", "size_bytes": 1048576 }` →

```json
{
  "file_id": "…",
  "upload_url": "https://minio.corp/bucket/…?X-Amz-Signature=…",
  "method": "PUT",
  "headers": { "Content-Type": "application/pdf" },
  "expires_at": "…", "max_size_bytes": 104857600
}
```

`POST /v1/media/upload-complete` ← `{ "file_id": "…" }` → `{ "id": "…", "status": "ready", "av_status": "pending", "name": "report.pdf", "mime_type": "…", "size_bytes": 1048576, "thumbnail_url": null }` — превью владельцу доступно до отправки. `GET /v1/media/{file_id}/url` → `{ "url": "https://minio.corp/…", "expires_in": 300 }`.

**Боты**

`POST /v1/bots` ← `{ "username": "deploy-bot", "full_name": "Deploy Bot", "description": "…" }` → `{ "user_id": "…", "username": "deploy-bot", "description": "…", "is_enabled": true, "created_at": "…" }`.

`POST /v1/bots/{bot_id}/tokens` ← `{ "name": "prod", "expires_at": null }` → `{ "id": "…", "token": "mt_9f3a…", "token_prefix": "mt_9f3a", "expires_at": null }` — токен в открытом виде показывается только здесь.

`GET /v1/bots/me` (Bearer `mt_…`) → объект бота. `GET /v1/bots/getUpdates?timeout=30&offset=1001` (long polling) →

```json
{
  "updates": [
    { "update_id": 1001, "type": "message.created", "chat_id": "…", "payload": { "message": { } } }
  ],
  "next_offset": 1002
}
```

При таймауте без событий: `{ "updates": [], "next_offset": 1001 }`. Отправка от имени бота — обычный `POST /messages` с Bearer-токеном бота.

**Поиск**

`GET /v1/search?q=отчёт&type=messages&chat_id=&author_id=&date_from=&date_to=` → `{ "items": [ { "type": "message", "chat_id": "…", "seq": 121, "message": Message } ], "next_offset": 20 }`; для `type=users|chats` элементы: `{ "type": "user", "user": User }` / `{ "type": "chat", "chat": Chat }`. Права: только чаты, где запрашивающий — участник (SQL-фильтр `JOIN chat_members`).

**Сессии (BFF)**

`GET /v1/auth/sessions` → `{ "items": [ { "id": "…", "platform": "web", "ip": "10.0.0.1", "user_agent": "…", "created_at": "…", "last_seen_at": "…", "current": true } ] }`; `DELETE /v1/auth/sessions/{id}` и `POST /v1/auth/logout-all` → 204.

**Админка**

- `GET /v1/admin/users?limit=50&offset=` → `{ "items": [User + { "last_login_at": "…" }], "next_offset": 50 }`.
- `POST /v1/admin/users` ← `{ "username": "petrov", "full_name": "Пётр Петров", "email": "petrov@corp.ru", "send_email": true }` → `User` + `{ "temporary_password": "…" }` при `send_email=false` (показывается один раз).
- `POST /v1/admin/users/import` (multipart CSV: `username,full_name,email`) → `{ "created": 24, "failed": [ { "row": 5, "error": "duplicate_username" } ] }`.
- `POST /v1/admin/users/{id}/reset-password` → `{ "temporary_password": "…" }` либо `{ "email_sent": true }`.
- `POST /v1/admin/users/{id}/disable|enable` → `User` со статусом `disabled|active`.
- `GET /v1/admin/stats` → `{ "dau": 320, "messages_per_day": 15400, "users_total": 1450, "chats_total": 980, "storage_bytes": 107374182400 }`.
- `GET /v1/admin/audit?limit=50&offset=` → `{ "items": [ { "id": 1001, "actor_id": "…", "action": "user.disabled", "entity_type": "user", "entity_id": "…", "metadata": {}, "ip": "…", "created_at": "…" } ], "next_offset": 50 }`.

### 8.3. Правила и лимиты

Значения по умолчанию в `app_settings`: текст ≤ 4096 символов; файл ≤ 100 МБ; ≤ 10 вложений на сообщение; аватар ≤ 5 МБ (image MIME); макс. участников группы — 10 000; пагинация: сообщения 50, чаты 50, поиск 20 на страницу; окно редактирования — без ограничения (конфиг); квота хранилища на пользователя — опциональный конфиг.

### 8.4. Поток отправки сообщения

```text
1. POST /v1/chats/{chat_id}/messages (Idempotency-Key)
2. Проверки: токен → пользователь → участие в чате → права → rate limit → лимиты
3. Транзакция: UPDATE chats (seq+1) → INSERT messages → message_attachments → message_mentions → INSERT outbox_events
4. Commit → fast path: публикация в Valkey Pub/Sub → мгновенный WS fanout онлайн-участникам
5. Worker (надёжный путь): push офлайн-участникам, бейджи, (этап 2: bot webhooks)
6. Клиент получает ответ с chat_id + seq
```

---

## 9. Realtime (WebSocket)

- `wss://…/ws`; авторизация: BFF cookie (web) или Bearer-токен в handshake (mobile); heartbeat 30 c.
- **Fast path**: после коммита транзакции модуль messages публикует событие в Valkey Pub/Sub → все инстансы api рассылают подписчикам чата; задержка ~десятки мс.
- **Надёжный путь**: строка в `outbox_events` → worker: push, бейджи, AV. At-least-once; дедуп на клиенте по `(chat_id, seq)`.
- События сервер → клиент: `message.new`, `message.updated`, `message.deleted`, `chat.updated`, `chat.member.joined`, `chat.member.left`, `chat.read`, `typing.start`, `typing.stop`, `presence.update`, `notification.badge`.
- События клиент → сервер: `typing.start|stop`, `sync.request`, heartbeat.
- **Синхронизация**: `sync.request` с `last_seq` по чатам:

```json
{
  "type": "sync.request",
  "chats": [{ "chat_id": "uuid", "last_seq": 1200 }]
}
```

Сервер отдаёт пропущенное из `messages` (не из лога событий) — просто и надёжно; reconnect не теряет сообщения.

- Presence: Valkey-ключи с TTL 60 c (обновляются heartbeat'ом); typing — только pub/sub, без хранения.
- `@all` — только админам чата при >100 участниках (порог в `app_settings`).

---

## 10. Уведомления

- Каналы: FCM (Android), APNs (iOS), Web Push (VAPID), in-app; токены в `devices`, чистка неактуальных по ответам FCM/APNs.
- **Правила отправки**: получатель — активный участник чата; чат не в mute; режим чата (`all|mentions|none`); не DND (`notification_settings.dnd_until`); упоминание или новое сообщение.
- **Оптимизация для больших групп**: батчинг и троттлинг в worker'е (не чаще N push/мин на пользователя), агрегация; полный текст в push — опция приватности; счётчики бейджей из `last_read_seq`.
- Требуется завести: проект Firebase, Apple Developer Account, VAPID-ключи; SMTP — корпоративный релей (для reset пароля; fallback — временные пароли от админа).

---

## 11. Файлы и медиа

- Поток: `upload-intents` (лимиты, MIME, размер) → presigned PUT в MinIO → `upload-complete` (HEAD-проверка, av_status) → файл готов; превью доступно владельцу до отправки.
- Вложение: клиент передаёт `file_id` при отправке сообщения → строка в `message_attachments` (≤10 на сообщение, владелец файла = отправитель).
- Аватары: `PATCH /v1/me {avatar_file_id}` — файл без сообщения.
- Доступ на скачивание: владелец файла | участник чата, где файл в сообщении | аватар пользователя; presigned GET 5 мин.
- Лимиты: размер (100 МБ по умолчанию, в `app_settings`), whitelist MIME, проверка магических байтов, sha256.
- Private bucket, SSE-S3, шифрование на стороне хранилища.
- Thumbnail'ы (Pillow) и AV-скан (ClamAV, опциональный compose-профиль) — в worker; `infected` → удаление объекта + аудит.
- Удаление сообщения → каскад `message_attachments`; объекты MinIO и строки `files` чистит worker при отсутствии ссылок.

---

## 12. Боты и интеграции

- Бот — пользователь `users.kind='bot'`; данные в `bots`; аутентификация — Bearer bot-token (в БД только sha256-хэш; токен в открытом виде показывается один раз; поддержка отзыва и срока).
- **Доставка событий — long polling** `GET /v1/bots/getUpdates?timeout=30&offset=`: бот читает `outbox_events WHERE seq > cursor` с фильтром по чатам, где состоит; курсор — на стороне бота.
- События: `message.created`, `message.updated`, `message.deleted`, `message.command`, `chat.member.joined`, `chat.member.left`, `bot.added_to_chat`, `bot.removed_from_chat`.
- Отправка/редактирование/удаление — обычными REST-эндпоинтами от имени бота; бот пишет только в чаты, где состоит.
- Команды: `/help`, `/deploy prod`, `/ticket create` — реестр в `bot_commands`, попадание в `message.command`.
- Права: создание/токены/удаление — `owner`/`admin` организации; добавление в группу — владелец/админ чата; DM с ботом — всем.
- Webhook'и (этап 2): подписки (`bot_subscriptions`), scopes, HMAC-подпись исходящих (`webhook_secret_ref`), retry с экспоненциальной задержкой, отключение бота при частых ошибках, SSRF-валидация `webhook_url` (запрет private-диапазонов).
- Безопасность: rate limit как у пользователя, аудит действий ботов, отключение при спаме.

---

## 13. Поиск

- **PostgreSQL FTS** с первого дня: `to_tsvector('russian', body)` (генерируемая колонка, GIN-индекс) — поиск по сообщениям; pg_trgm по `users.full_name` — поиск людей; поиск по чатам по title.
- Фильтры: тип (messages|chats|users), чат, автор, диапазон дат; пагинация 20/страница.
- Права: SQL-фильтр по членству запрашивающего в чатах.
- Рост (>5–10 млн сообщений): OpenSearch — индексирование через outbox/worker, отдельные индексы, проверка прав на бэкенде, без прямого доступа клиентов.

---

## 14. Безопасность

- **Аутентификация**: пароли только в Keycloak (политика сложности, brute-force, опциональный TOTP); OIDC Authorization Code + PKCE; короткий access (5 мин) + refresh-ротация; серверные сессии с отзывом; не хранить токены в открытом виде.
- **Авторизация**: проверка ролей и членства на каждом запросе; бизнес-права в БД мессенджера.
- **Защита данных**: TLS везде; cookie HttpOnly/Secure/SameSite + CSRF-токен; SSE-S3 для файлов; минимизация ПДн в логах; маскирование email/телефона в админ-просмотре для роли member; секреты — docker secrets/env (Vault — позже).
- **Rate limits** (Valkey, sliding window): login 10/мин/IP (плюс brute-force Keycloak); сообщения 60/мин/пользователь; создание чатов 10/ч; загрузки 20/ч; добавление участников ≤100/операция.
- **Invite-ссылки**: 128-битный код, rate limit на `/v1/invites/{code}/join`, срок/лимит использований/отзыв; join только для активных пользователей.
- **Интеграции**: подпись исходящих webhook'ов (HMAC, этап 2); SSRF-валидация `webhook_url`; анти-спам ботов (лимиты, квоты, аудит).

### Аудит

События `audit_logs`: `user.login.success|failed` (в `login_events`), `user.disabled|enabled`, `user.created`, `chat.created|deleted`, `chat.member.added|removed`, `message.deleted` (в т.ч. админом), `bot.created|disabled`, `bot.token.revoked`, `admin.settings.updated`, `file.infected`. Экспорт в SIEM — этап 4.

---

## 15. Наблюдаемость

- **Метрики** (Prometheus): RPS, latency, ошибки 4xx/5xx, активные WS-подключения, время доставки сообщений (created_at → событие), длина unpublished-очереди outbox, ошибки доставки push/ботов, DAU.
- **Логи**: JSON → Loki (API, worker, аутентификация, админ-действия).
- **Трейсинг**: OpenTelemetry — этап 3 (не блокирует запуск).
- **Алерты**: down-компоненты, рост 5xx, outbox lag, диск/память.

---

## 16. Отказоустойчивость и деградация

| Отказ | Поведение |
|---|---|
| PostgreSQL | Сервис недоступен (единая точка истины); бэкапы + восстановление обязательны |
| Valkey | Деградация realtime: нет WS fanout/typing/presence, потеря BFF-сессий (повторный вход), задержка push; rate-limit в fail-open. Запись сообщений в Postgres продолжается; клиенты компенсируют resync через REST |
| Keycloak | Новые логины и refresh невозможны; выданные access-токены работают (JWKS кэшируется) — сессии и WS живут |
| MinIO | Отказ загрузки/скачивания файлов; текстовый обмен работает |
| Инстанс api | Клиенты переподключаются и синхронизируются по последнему seq в чате; pub/sub fire-and-forget, гарантия доставки — resync |
| Worker | Push, AV, thumbnail'ы, retention, бейджи задерживаются; outbox копится и догоняет; отправка сообщений не страдает |
| SMTP | Reset пароля письмом недоступен; fallback — временный пароль от админа |

---

## 17. Дорожная карта

- **Этап 0. Каркас**: репозиторий (backend/web/mobile/deploy), docker-compose + realm-export Keycloak, alembic baseline, CI (ruff/mypy/pytest), nginx TLS, bootstrap-админ, `/healthz` + `/metrics`, структурированные логи.
- **Этап 1. MVP**: BFF-вход + Flutter-вход (PKCE), JIT-синк пользователей, профиль, direct/групповые чаты, участники и роли, invite-ссылки, сообщения (seq, идемпотентность, редактирование/удаление, reply, пересылка, markdown/mentions/@all), файлы + превью + аватары, Web Push + in-app + бейджи (FCM/APNs — следом), FTS-поиск, боты (токены, long polling getUpdates, команды), админка (создание/блокировка/CSV/сброс пароля/статистика/аудит/сессии), retention-флаг.
- **Этап 2. Боты и интеграции**: webhook-доставка (subscriptions, scopes, HMAC-подпись, retry/backoff), карточки, реакции, закрепление сообщений, расширенный аудит.
- **Этап 3. Масштабирование**: нагрузочное тестирование (k6/locust: 2000 WS-соединений, чат 1000+ участников), партиционирование `messages` при необходимости, OpenSearch при >5–10 млн сообщений, HA Postgres (стриминг-реплика), AV-контур, OpenTelemetry, автомаппинг LDAP-групп на чаты.
- **Этап 4. Корпоративные функции**: треды, каналы, голосовые/видеозвонки (LiveKit/SFU), расширенные политики ретенции, экспорт, legal hold, гостевой доступ, DLP, SIEM-экспорт аудита.

Вне скоупа (осознанно): мультиорганизационность (при необходимости — миграция с добавлением `org_id`), телефонный вход, E2E-шифрование.

---

## 18. Риски

| Риск | Мера |
|---|---|
| Python/GIL: CPU-задачи тормозят event loop | thumbnail/AV/сжатие — только в worker; `--scale api=N`; профильная нагрузка на этапе 3 |
| Keycloak — SPOF входа | restart policy, бэкапы realm, мониторинг; при падении существующие сессии и WS живут |
| Расхождение LDAP ↔ users | ежечасный синк + JIT при входе + проверка статуса на каждом запросе (кэш 30 c) |
| Fanout в больших группах | батчи/троттлинг push, асинхронная обработка через outbox, кэш участников |
| Спам от ботов | scopes (этап 2), лимиты на бота, аудит, отключение при ошибках |
| Подбор invite-кодов | 128-битная случайность + rate limit на join |
| Курсор бота отстал за retention outbox | бот делает resync с текущего события; состояние чата восстанавливается из `messages` |
| Нет SMTP → reset пароля недоступен | fallback: админ выдаёт временный пароль; уточнить корпоративный релей на этапе 0 |
| FCM/APNs требуют аккаунтов Google/Apple | завести на этапе 0, до этапа 1 |
| WebSocket за nginx | конфиг upgrade/timeout; автопереподключение + `sync.request` на клиенте |
| Рост `messages` | партиционирование на этапе 3 при >50–100 млн строк; отдельный message store — при дальнейшем росте |

---

## 19. Валидация

Dev-скрипты (требуют запущенного стека `docker compose up -d postgres valkey minio keycloak api`):

- `backend/scripts/dev_smoke.py` — сервисный уровень: dedup direct-чатов, seq, идемпотентность, mentions, редактирование, «прочитано», tombstone-удаление, S3 presigned PUT/GET, права на файлы.
- `backend/scripts/dev_token_check.py` — цепочка Keycloak → JWKS → `verify_access_token` (sub/aud) → userinfo.
- `backend/scripts/dev_login_check.py` — полный браузерный флоу: логин через Keycloak → callback → cookie-сессия → JWT-создание пользователя → `/v1/me`.

- **Unit**: матрица прав (роль организации × роль чата × владелец объекта), генерация seq, идемпотентность, парсинг mentions, правила уведомлений, лимиты, пересылка.
- **Integration** (pytest + testcontainers: pg, valkey, keycloak, minio): вход через тестовый realm (LDAP-мок), отправка/получение WS-событий, upload → presigned → attachment, outbox → worker → pub/sub, отзыв сессии, ретрай с тем же Idempotency-Key без дубля, join по invite (срок/лимит/отзыв), бот получает событие через long polling и отвечает.
- **E2E**: два браузера + Android-эмулятор: вход → чат → сообщение → доставка < 2 c → push → бот отвечает на команду → блокировка пользователя админом → доступ закрыт ≤ 30 c.
- **Load** (этап 3): 2000 WS-соединений, burst в чат 1000 участников, p95 доставки < 2 c, outbox lag < 5 c.

---

## 20. Открытые вопросы (не блокируют реализацию)

1. SMTP-релей для писем (reset пароля) — уточнить доступность на этапе 0; fallback заложен.
2. Точные имена LDAP-атрибутов (sAMAccountName vs userPrincipalName) и маппинг групп — фиксируются при настройке федерации.
