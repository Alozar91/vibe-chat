# Firebase — инструкция по созданию проекта (пререквизиты мобильного, Docs/android.md §6)

Проект нужен для FCM (push-уведомления, этапы 6–7 мобильной реализации).
Делается один раз вручную — консоль Firebase требует Google-аккаунт.

## 1. Создание проекта (5 минут)

1. Открыть https://console.firebase.google.com → **Add project**
2. Имя: `vibe-chat` (или любое); Google Analytics — **отключить** (не нужен для FCM)
3. Create project

## 2. Регистрация Android-приложения

1. Project Overview → иконка **Android** (Add app → Android)
2. **Android package name**: `ru.vibe.chat.app` — точно как в `Docs/android.md` §4
   (applicationId; другое имя → FCM не свяжется с приложением)
3. App nickname: `vibe-chat-android`; SHA-1/SHA-256 — **пропустить** (не нужен для FCM без App Check)
4. **Register app** → скачать **`google-services.json`**
5. Положить файл в `mobile/google-services.json` И копию в `mobile/android/app/google-services.json`
   (gradle-плагин `com.google.gms.google-services` читает именно android/app/). В git НЕ коммитить —
   там project id/ключи; коммитим `mobile/google-services.json.example`-заглушку, см. ниже)
   Примечание: `android/` коммитится (bare workflow), но `google-services.json` по-прежнему
   игнорируется и на новой машине копируется вручную из корня.

## 3. Проверка

В консоли: Project settings → Your apps → `ru.vibe.chat.app` должен быть в списке.
API, который нас интересует: Firebase Cloud Messaging — включён по умолчанию для Android.

## 4. Что делает этот файл на стороне сборки

- `expo prebuild` / `npx expo run:android` подхватывает его через плагин
  `@react-native-firebase/app` (настроен в `mobile/app.json` → plugins)
- Без файла этапы 6–7 (пуши) не соберутся; этапы 1–5 работают без него

## Важно для эмулятора

FCM работает на AVD с образом **Google Play** (у нас `Pixel_5_API_35` — подходит,
см. `Docs/android.md` §6). На образах без Google Play (AOSP) пуш не придёт.

## Self-hosted ограничение (§9 Docs/android.md)

FCM — внешний сервис Google. Для корпоративного самодостаточного варианта
в будущем возможен UnifiedPush/own gateway — решение отложено, MVP на FCM.
