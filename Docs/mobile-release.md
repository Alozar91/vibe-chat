# Релизная сборка мобильного приложения (Android)

> Ранбук сборки и раздачи release-APK. Архитектурный контекст — `Docs/android.md` (§4 — идентификация и версии, §3.7 — env-конфиг, §3.8 — гейт версии, §9 — грабли); продуктовая правда — `Docs/concept.md`. Этот файл — пошаговая процедура: что, в каком порядке и как проверить.

## 1. Предпосылки (один раз, эта машина)

| Компонент | Значение | Где |
|---|---|---|
| JDK 17 | `~/.local/opt/jdk-17.0.21.1+2` | `JAVA_HOME` в `~/.profile` |
| Android SDK | `~/.local/opt/android-sdk` (platforms;android-35, build-tools;35.0.0, ndk;27.1.12297006) | `ANDROID_HOME` в `~/.profile` |
| Gradle-зеркала | нужны **только Windows-сборкам**: `C:\Users\SeregaPC\.gradle\init.d\mirrors.gradle` | из WSL не читается (`dl.google.com` отсюда доступен) |
| Keystore | `mobile/android/keystores/` — вне git | см. §3 |

Перед сборкой: `. ~/.profile` (WSL), `node_modules` на месте, `tsc --noEmit` зелёный.

## 2. Версии — правило бампа

- `versionName` — семантическая, `versionCode` — монотонный счётчик, **бамп на каждой release-сборке**, в **двух местах синхронно**:
  - `mobile/app.json` → `expo.version` и `expo.android.versionCode`
  - `mobile/android/app/build.gradle` → `versionCode` / `versionName` (~строки 95–96)
- Текущее состояние: **`1.0.3` / code `4`** (`1.0.0`/1 → `1.0.1`/2 → `1.0.2`/3 → `1.0.3`/4; 1.0.3 — self-host: экран подключения, динамический конфиг, per-app FCM).
- Клиент сравнивает с сервером `versionName` (семантика X.Y.Z, `src/services/app-version.ts`); `versionCode` в гейте не участвует.

```bash
# бамп 1.0.1 → 1.0.2 (пример)
cd mobile
sed -i 's/versionCode 2/versionCode 3/; s/versionName "1.0.1"/versionName "1.0.2"/' android/app/build.gradle
python3 - <<'EOF'
import json
p = 'app.json'
d = json.load(open(p))
d['expo']['version'] = '1.0.2'
d['expo']['android']['versionCode'] = 3
json.dump(d, open(p, 'w'), indent=2, ensure_ascii=False)
open(p, 'a').write('\n')
EOF
```

## 3. Keystore (подпись)

- Файлы: `mobile/android/keystores/vibe-release.keystore` + `keystores/keystore.properties` (`storeFile`/`storePassword`/`keyAlias`/`keyPassword`, chmod 600). Оба — **вне git** (`mobile/android/.gitignore`).
- **Бэкап вне репо** (обязателен): `~/.local/opt/keystore-backup/vibe-chat/`.
- Потеря keystore = пользователи не смогут обновиться поверх (смена подписи блокирует установку) — только uninstall/reinstall с потерей локального кэша и push-токенов. Восстановление на новой машине — скопировать **оба** файла из бэкапа в `mobile/android/keystores/`.
- `build.gradle` применяет release-signing **только при наличии** `keystore.properties`; без них сборка даёт `app-release-unsigned.apk` — это осознанный сигнал «окружение не настроено», молча подписывать debug-ключом нельзя.
- Характеристики текущего ключа: RSA 2048, alias `vibe-release`, валидность ~30 лет (10950 дней), DN `CN=Vibe Chat Release, OU=IT, O=Vibe Chat, C=RU`.

## 4. Сборка

```bash
. ~/.profile
cd mobile/android
./gradlew assembleRelease
# → app/build/outputs/apk/release/app-release.apk
```

Дальше — сохранить артефакт с именем версии (раздача по имени):

```bash
cp app/build/outputs/apk/release/app-release.apk \
   ~/.local/opt/apk/vibe-chat/vibe-chat-<version>.apk
```

Если правился нативный код (манифест, gradle, нативные зависимости) — сборка подхватит сама; если правился **только JS** — Gradle может посчитать таск up-to-date, см. §7 «env не запёкся».

## 5. Проверка артефакта (перед раздачей)

```bash
cd mobile/android
BT=~/.local/opt/android-sdk/build-tools/35.0.0

# 1) версия и package
$BT/aapt dump badging app/build/outputs/apk/release/app-release.apk | grep '^package'
# → versionCode='N' versionName='X.Y.Z' — совпадает с бампом

# 2) подпись — наш сертификат, не debug
$BT/apksigner verify --print-certs app/build/outputs/apk/release/app-release.apk | head -2
# → CN=Vibe Chat Release, OU=IT, O=Vibe Chat, C=RU

# 3) статический env: с 1.0.3 конфиг ДИНАМИЧЕСКИЙ (экран подключения) — статических
#    EXPO_PUBLIC_* в бандле быть НЕ должно (исключение — dev-override LiveKit):
unzip -p app/build/outputs/apk/release/app-release.apk assets/index.android.bundle \
  | strings | grep -c "EXPO_PUBLIC_API_BASE"
# → 0 (наличие = в бандл попала старая сборка — собирать бессмысленно)
```

Smoke на эмуляторе: uninstall старого → `adb install` → экран подключения (release
требует https, кроме dev-адресов localhost/10.0.2.2 — зеркалит NSC) → подключить
сервер → логин → чаты → отправка сообщения. Приложение требует https, кроме dev-адресов
`localhost`/`10.0.2.2` (зеркалит cleartext-исключения NSC — эмулятор/adb reverse).

## 6. Установка и проверка обновления поверх

```bash
# обновление поверх (та же подпись) — данные/кэш/сессия сохраняются
adb -s <device> install -r ~/.local/opt/apk/vibe-chat/vibe-chat-<version>.apk

# смена подписи (debug ↔ release) поверх невозможна — сначала uninstall
```

MIUI (Xiaomi): при первой `adb install` на экране телефона — системное «Установить это приложение через USB?» → тап **«Установить»** (опционально «Запомнить выбор»); иначе «Отклонен запрос на установку».

Проверено (2026-11-26): 1.0.0 → 1.0.1 `install -r` на эмуляторе и телефоне — обновление работает, сессия и чаты на месте; смоук обеих сторон (эмулятор — admin, телефон — pushtest1).

## 7. Гейт версии — как проверить (e2e)

1. На бэкенде задать минимум: дописать в `backend/.env` `APP_MIN_APP_VERSION=99.0.0`, перезапустить uvicorn.
2. Холодный старт приложения → блокирующий экран «Требуется обновление» (текст содержит own/min версии, «Проверить снова»).
3. Убрать переменную, перезапустить бэкенд → тап «Проверить снова» → приложение открывается **без рестарта**.
4. Fail-open (проверено тем же прогоном): `min_version` пуст или сервер недоступен → приложение работает.

Нелинейность: экран блокирует **всё** (вход и навигация недоступны) — это сознательно; ссылка на скачивание берётся из `EXPO_PUBLIC_APP_DOWNLOAD_URL`, не задана — «Ссылку на новую версию выдаёт администратор».

## 8. Раздача

- APK с собственного keystore **не требует** Google Play, аккаунта разработчика ($25) и Google-аккаунта у пользователей. Единственный Google-аккаунт в проекте — Firebase (FCM-пуши, уже настроен); пуши работают и для sideload-APK, но только на устройствах с Google Play Services.
- Каналы: прямая ссылка на APK (стенд/HTTP-сервер), MDM, ручная передача. Пользователь один раз включает «Установка неизвестных приложений» для браузера/проводника; Play Protect может предупредить — «всё равно установить».
- Ссылка для гейта: `EXPO_PUBLIC_APP_DOWNLOAD_URL` (запекается при сборке; не задана — текст-подсказка). Обновление в рантайме (баннер «доступна новая версия») — отложено (§3.8 андроид-дока).

## 9. Известные грабли

- **env не запёкся** → «EXPO_PUBLIC_… не задан» при старте release-сборки. Причина: доступ к env в коде — **только статический** (`process.env.EXPO_PUBLIC_X`); babel-инлайнер Expo не разворачивает динамические `process.env['EXPO_PUBLIC_' + name]` (в debug его выручает рантайм-гидратация от dev-сервера, в release её нет). Лечение: статические обращения в `config.ts`; проверка — §5 п.3. Если Gradle не пересобрал бандл после правки только конфига/env — дёрнуть содержимое JS-файла (Gradle хеширует контент, `touch` не помогает) или `./gradlew createBundleReleaseJsAndAssets --rerun-tasks`.
- **Cleartext в release** — сеть режется NSC (`app/src/main/res/xml/network_security_config.xml`): https обязателен по умолчанию, cleartext разрешён только `localhost` (adb reverse), `10.0.2.2` (эмулятор), `192.168.1.64` (dev-LiveKit, машинно-специфичен — при смене машины править XML). Симптом: fetch/WS молча падают в release при рабочем debug. Новый dev-хост — добавить в XML.
- **debug-версия поверх release** (и наоборот) — не ставится: сначала `uninstall` (потеря локального состояния ожидаема).
- **Prebuild затирает ручные правки** `android/app/build.gradle` (signing) и манифеста (NSC) — `android/` в git; после `expo prebuild` сверить §3 и NSC заново.
- Пуши: push-токены переживают обновление (Keystore/MMKV сохраняются), но не uninstall.
