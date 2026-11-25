# Мобильный клиент vibe-chat (Android)

Реализация по `Docs/android.md` (проектная правда — там; этот README — краткая навигация).

## Быстрый старт

```bash
cd mobile

# 1. env-конфиг
cp .env.example .env        # dev-профиль: эмулятор → 10.0.2.2 (loopback хоста; бэкенд :8002, Silo :9000, KC :8081)

# 2. зависимости
npm ci

# 3. генерация нативного проекта (expo prebuild → android/)
npx expo prebuild

# 4. сборка + запуск на эмуляторе (AVD Pixel_5_API_35)
npx expo run:android
```

Metro (hot reload): `npx expo start`. Локальный стенд для «зелёной» диагностики:
`docker compose -f deploy/docker-compose.yml up -d` + бэкенд
`cd backend; .venv/Scripts/python -m uvicorn app.main:app --host 0.0.0.0 --port 8002`.

## Структура (Docs/android.md §5)

```
mobile/
  app/                  # Expo Router: экраны (index, login, (app)/chats)
  src/
    api/                # REST-клиент + типы (копия контракта frontend)
    stores/             # Zustand: session, ws-состояние
    services/           # api-client, config, diagnostics, ws-client, media-cache...
    hooks/              # TanStack Query
    push/               # FCM (этап 6–7)
  app.json              # applicationId ru.vibe.chat.app, scheme vibechat://
  .env.example          # профили dev / стенд
  docs/                 # firebase-setup, prerequisites
```

## Пререквизиты

См. `docs/prerequisites.md`. Кратко: SDK ✅, Keycloak-клиент `mobile` ✅ (стенд),
Firebase — вручную к этапу 6 (`docs/firebase-setup.md`).

## Этапы

Реализация поэтапная (Docs/android.md §8): 1 каркас ✅ → 2 auth ✅ → 3 чаты ✅ →
4 realtime ✅ → 5 вложения ✅ → 6 бэкенд-пуши → 7 клиент-пуши → 8 релизный APK.
Текущий этап см. в AGENTS.md «Статус».

## Ручное тестирование чатов/realtime/вложений на эмуляторе (этапы 3–5)

Проверено e2e (2026-11-20): отправка/пагинация/оффлайн-кэш, WS-доставка < 1 c,
typing, presence (heartbeat), реконнект после airplane mode с догонянием
(`updated_after`), upload-флоу Silo (Photo Picker → presigned PUT → complete →
сообщение с thumbnail в ленте), прогресс и отмена upload, лимит 100 МБ до PUT
(Alert), медиа-кэш переживает перезапуск (файлы в `cache/vibe-media/`).

Подводные камни upload-флоу (решения в `Docs/android.md` §9):

- **`adb reverse tcp:9000 tcp:9000` обязателен** — presigned PUT подписан на
  `APP_SILO_PUBLIC_URL` (host входит в подпись S3v4); в dev это `localhost:9000`,
  из эмулятора доступен только через reverse. Без него — «network error».
- **`asset.fileSize` пикера врёт** — Content-Length ≠ подписанному → 403;
  размер берётся из `blob.size` после `fetch(uri)`.
- **Проверка лимита до fetch** — fetch 108 МБ `content://` падает в RN
  («Network request failed»), не доходя до нашей валидации.
- **Консоль Hermes не видна в Metro-логе** — для диагностики из приложения
  надёжнее выводить текст ошибки прямо в UI (панель вложений) или logcat
  (`logcat --pid=$(pidof ru.vibe.chat.app)`); `console.log` теряется.
- **Fast Refresh не переинициализирует не-компонентные модули** (`upload.ts`,
  замыкания dispatch) — после правок сервисов полный reload
  (`POST http://localhost:8081/reload`) или force-stop приложения.

## Ручное тестирование auth на эмуляторе (этап 2)

Проверено (2026-11-19): регистрация (оба режима, 409/422-обработка), логин
ROPC, logout, восстановление сессии после force-stop, повторный вход другим
пользователем, **PKCE-fallback e2e** (при отключённых direct grants: Custom Tab →
KC-форма → redirect `vibechat://callback` → обмен кода → «Чаты»).

Хрупкости adb-управления, экономящие часы:

- **Gboard рисует стилус-оверлей** («Try out your stylus» + плавающий тулбар) —
  он перехватывает фокус и сдвигает лейаут, текст уходит не в то поле. Лечится
  `adb shell am force-stop com.google.android.inputmethod.latin` или перезапуском
  приложения; надёжнее сразу закрыть клавиатуру `input keyevent 111` (ESC)
- **Координаты «плывут»**: при открытой клавиатуре весь лейаут сдвигается.
  Рабочий метод: перед каждым вводом `adb shell uiautomator dump /sdcard/ui.xml`
  + `adb pull` + regex по `EditText` bounds → точные координаты. Пример разбора:
  `[regex]::Matches($xml, '<node[^>]*class="android.widget.EditText"[^>]*>')`
- **Chrome Custom Tab (PKCE-форма KC)**: uiautomator **не видит** WebView-поля
  (дамп пуст по EditText). Рабочий приём: первый `input keyevent 61` (TAB) даёт
  фокус на поле Username (оранжевая рамка — проверить скриншотом), дальше
  `input text` → `keyevent 61` (TAB на Password) → `input text`; сабмит —
  `input keyevent 66` (Enter: кнопка Sign In перекрыта клавиатурой, тап не
  достаёт). Первый запуск Chrome требует онбординга («Use without an account»).
- **ADB-туннели обязательны**: `adb reverse tcp:8081 tcp:8081` (Metro) **и**
  `adb reverse tcp:8080 tcp:8080` (KC: форма PKCE открывается на localhost:8080
  и после логина KC редиректит на `frontendUrl`=localhost:8080; без reverse —
  ERR_CONNECTION_REFUSED). После `adb kill-server` устанавливать оба заново.
  В `mobile/.env` dev-KC задан как `http://localhost:8080` (не 10.0.2.2!):
  весь PKCE-флоу должен ходить на один хост, иначе KC теряет cookies
  («Restart login cookie not found»)
- Очистка поля: tap по полю → `input keycombination 113 29` (Ctrl+A) →
  `input keyevent 67` (DEL)
- Скриншоты: `adb shell screencap -p /sdcard/x.png` + `adb pull` в temp-каталог
- Metro хрупок: перезапускать после `npm install`; при «Port 8081 is being used»
  убить слушатель (`Get-NetTCPConnection -LocalPort 8081 | Stop-Process`); правки
  node_modules под живым Metro ломают бандл — перезапуск с `--clear`;
  **«Compiling JS failed» с плавающими позициями** (не воспроизводится hermesc
  локально на выкачанном бандле) = битый adb-туннель/обрезанный бандл:
  `adb kill-server` → `adb start-server` → свежий `reverse tcp:8081`

## Известные особенности окружения (эта машина)

- `dl.google.com` и `plugins.gradle.org` недоступны (connection reset) —
  глобальный init-скрипт `C:\Users\SeregaPC\.gradle\init.d\mirrors.gradle`
  перенаправляет google()/plugin-репозитории на зеркало Aliyun. Без него
  сборка падает на скачивании зависимостей; файл машинно-специфичный,
  в git не входит.
- NDK 27.1.12297006 установлен вручную (sdkmanager) — Gradle его переиспользует.
- `query-string` — прямая зависимость (8.2.0): нужна fork-файлу expo-router,
  у expo-router v5.1 она не объявлена; v10+ не совместима с Hermes
  (regex-флаг `v`) — не поднимать.
- `expo-asset/file-system/font/keep-awake` — прямые зависимости (гарантирует
  hoisting для autolinking; иначе «Cannot find native module 'ExpoAsset'»).
