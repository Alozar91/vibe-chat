"""Конфигурация бэкенда — pydantic-settings, префикс APP_* (Docs/concept.md §13)."""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    # Приложение
    app_name: str = "vibe-chat-backend"
    log_level: str = "INFO"

    # PostgreSQL
    db_url: str = "postgresql+asyncpg://vibe:vibe@localhost:5432/vibe"

    # Valkey
    valkey_url: str = "valkey://localhost:6379/0"

    # Silo (S3-совместимое хранилище)
    silo_internal_url: str = "http://localhost:9000"
    # Публичный адрес для presigned URL (входит в подпись S3, §13):
    # scheme://host[:port] БЕЗ пути — системный nginx отдаёт Silo по /vibe-files/
    silo_public_url: str = "http://localhost:9000"
    silo_access_key: str = ""
    silo_secret_key: str = ""
    silo_bucket: str = "vibe-files"

    # Keycloak
    keycloak_url: str = "http://localhost:8080"
    keycloak_realm: str = "vibe-chat"
    keycloak_audience: str = "backend-api"
    # Admin API для инвайт-регистрации (§5): confidential client с ролью
    # realm-management/manage-users; пусто — регистрация выключена (503)
    keycloak_admin_client_id: str = "backend-admin"
    keycloak_admin_client_secret: str = ""

    # Файлы
    presign_ttl_seconds: int = 3600
    file_pending_ttl_hours: int = 24
    file_orphan_days: int = 7
    max_file_size_bytes: int = 100 * 1024 * 1024  # 100 МБ (§7 — конфигом)

    # Сообщения
    edit_window_hours: int = 24  # окно редактирования (§6)

    # Регистрация (§5): открытый режим — POST /auth/register без инвайт-кода.
    # Default false: инвайт-режим (коды платформенного админа) сохраняется;
    # включается на конкретной площадке env'ом (APP_OPEN_REGISTRATION=true)
    open_registration: bool = False

    # Звонки (LiveKit, §17): пустой api_key/secret — звонки выключены (503 на /calls/token)
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_ws_url: str = "ws://localhost:7880"  # публичный адрес WS-сигналинга для клиентов
    call_ring_timeout_seconds: int = 45  # ringing дольше — ended (cleanup, §17)

    # Пуши (Docs/android.md §3.8, этап 6): драйвер off | console (эмуляция) | fcm
    push_driver: str = "off"
    # fcm: путь к SA-ключу Firebase (deploy/secrets/firebase-sa.json, не в git) + project_id
    fcm_credentials_file: str = ""
    fcm_project_id: str = ""

    # Минимальная/актуальная версия мобильного клиента (§3.8, этап 8):
    # клиент при старте сравнивает свою версию с min_version — меньше: блокирующий экран
    min_app_version: str = ""
    latest_app_version: str = ""

    # Server selection / self-host (концепция §19): discovery /server/info
    server_name: str = ""  # человекочитаемое имя инсталляции (пусто = клиент покажет hostname)
    # Кодовое слово сервера (фейс-контроль, §19.5): опционально; пусто = выключено.
    # Неаутентифицированные эндпоинты (/server/info, /auth/register, /app/version)
    # требуют заголовок X-Vibe-Join; constant-time + rate-limit на неуспешные.
    join_code: str = ""
    # Ссылка на раздачу APK этой инсталляции (раньше EXPO_PUBLIC_APP_DOWNLOAD_URL клиента)
    # Поле названо с app_ (упало бы в APP_APP_…), поэтому env через AliasChoices:
    # принимаем APP_DOWNLOAD_URL (канонично) и APP_APP_DOWNLOAD_URL (для совместимости).
    app_download_url: str = Field(
        default="", validation_alias=AliasChoices("APP_DOWNLOAD_URL", "APP_APP_DOWNLOAD_URL")
    )
    # Firebase-конфиг КЛИЕНТА (google-services.json) для /server/info → рантайм-инициализация
    # Firebase на клиенте (§19.6). Не секрет (публичные идентификаторы). Путь к файлу.
    firebase_config_path: str = ""
    fcm_client_package: str = "ru.vibe.chat.app"
    # KC-адрес ДЛЯ КЛИЕНТОВ в /server/info (§19.4): пусто = keycloak_url.
    # Случай NAT/dev: бэкенд валидирует issuer по keycloak_url, а клиент ходит
    # к Keycloak по другому маршруту (эмулятор: 10.0.2.2:8080 при localhost
    # на хосте). В канонической one-origin-схеме (/kc) не задан.
    public_keycloak_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
