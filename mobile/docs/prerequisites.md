# Prerequisites для мобильной разработки (этапы из Docs/android.md §8)

## Статус пререквизитов

| Пререквизит | Статус | Когда нужен |
|---|---|---|
| Node.js ≥ 20, JDK 17, Android SDK, AVD | ✅ установлены (§6), NDK 27.1.12297006 | этап 1 |
| Клиент `mobile` в realm-export | ✅ добавлен (`deploy/keycloak/realm-export.json`) **и применён на стенде вручную** | этап 2 |
| Настройки KC для ROPC | ✅ required actions отключены + `frontendUrl` (см. ниже), зафиксировано в realm-export | этап 2 |
| Firebase-проект + `google-services.json` | ⬜ вручную (`mobile/docs/firebase-setup.md`), заглушка — `google-services.json.example` | этапы 6–7 |
| coturn | ⬜ отложен (звонки работают, кроме симметричных NAT) | следующие итерации (звонки) |

## Этап 1 (каркас) — выполнен ✅ (2026-11-19)

Expo dev build собирается и работает на эмуляторе `Pixel_5_API_35`:

- `expo prebuild` + `gradlew assembleDebug` — BUILD SUCCESSFUL; APK ставится, Metro подключается (hot reload)
- диагностика конфига «зелёная» против локального стенда (бэкенд :8002, Silo :9000 через `10.0.2.2`), guard ведёт на экран входа
- нюансы окружения (зеркала Gradle, NDK, pinned-зависимости) — в `mobile/README.md` раздел «Известные особенности окружения»

## Этап 2 (auth) — выполнен ✅ (2026-11-19)

ROPC-логин, нативная регистрация (оба режима), logout, восстановление сессии,
повторный вход другим пользователем — все проверены на эмуляторе против
локального стенда (подробности DoD — `Docs/android.md` §8):

- регистрация через форму: 201 + автовход; ошибки 409 («Имя пользователя уже
  занято») и 422 показаны корректно; открытый режим — `APP_OPEN_REGISTRATION=true`
- логин ROPC: форма → KC token endpoint → токены в Keystore (react-native-keychain,
  Android Keystore) → `/users/me` → экран чатов
- logout: revoke + полная очистка → экран входа
- восстановление сессии: после `adb shell am force-stop` приложение открывается
  сразу на «Чатах» (refresh из Keystore, в логе бэкенда свежий `GET /users/me 200`)
- повторный вход другим пользователем: OK
- **PKCE-fallback e2e** (2026-11-19): при `directAccessGrantsEnabled=false` ROPC
  вернул `unauthorized_client` → приложение открыло Chrome Custom Tab с KC-формой
  → логин → redirect `vibechat://callback` вернулся в приложение → код обменян на
  токены → `/users/me 200` → «Чаты»; сессия из PKCE-токенов восстанавливается
  после force-stop (refresh из Keystore). После проверки direct grants возвращены.

**Подводный камень PKCE в dev — два хоста KC.** Форма в Custom Tab открывалась на
`10.0.2.2:8080` (EXPO_PUBLIC_KC_URL), а после логина KC редиректил на `frontendUrl`
=`localhost:8080` → сессионные cookies KC (AUTH_SESSION_ID и др.) привязаны к хосту,
для `localhost` их нет → «Restart login cookie not found». Лечение: весь флоу на
одном хосте — `EXPO_PUBLIC_KC_URL=http://localhost:8080` (работает из эмулятора
через `adb reverse tcp:8080 tcp:8080`; iss токенов совпадает с бэкендом).

**Настройки KC, без которых ROPC не работает** (все зафиксированы в
`deploy/keycloak/realm-export.json`):

1. **Все required actions отключены** (`enabled: false`) — при любом
   включённом action KC отвечает `invalid_grant: Account is not fully set up`
   на token-запрос (ROPC не может выполнить интерактивные actions)
2. **`frontendUrl` realm'а** — определяет `iss` токенов; бэкенд валидирует iss
   по `APP_KEYCLOAK_URL`, значения должны совпадать. В dev —
   `http://localhost:8080` (эмулятор ходит на `10.0.2.2:8080`, но iss от хоста
   запроса не зависит); на стенде — `https://домен:8444`. Плейсхолдер
   `${VIBE_KC_FRONTEND_URL}` подставляется из compose-env
3. Клиент `mobile`: public + `directAccessGrantsEnabled` (см. выше)

Заметки для ручного тестирования на эмуляторе — в `mobile/README.md`
(Gboard-оверлей стилуса, uiautomator-координаты, IME).

## Клиент `mobile` в Keycloak (готово, применён на стенде)

В `deploy/keycloak/realm-export.json` добавлен public-клиент `mobile`:

- `directAccessGrantsEnabled: true` — ROPC-логин из нативной формы (основной флоу, §3.2)
- `standardFlowEnabled: true` + `pkce.code.challenge.method: S256` + redirect
  `vibechat://callback` — PKCE-fallback
- `defaultClientScopes` включает `backend-api` — audience mapper (правило AGENTS §13)
- Пользователи общие с вебом: один realm, один backend-api audience

**На стенде клиент добавлен вручную через Admin Console** (2026-11-19) —
`--import-realm` в KC 26 не обновляет существующий realm, поэтому ручное
добавление было единственным способом без пересоздания realm'а (и потери
KC-учёток). Файл realm-export.json содержит того же клиента для
воспроизводимости при будущих чистых деплоях.

## Firebase (нужно вручную)

Инструкция: `mobile/docs/firebase-setup.md`. Итог — файл
`mobile/google-services.json` (не коммитится) с package name
`ru.vibe.chat.app`. До этого этапы 1–5 собираются без него.
