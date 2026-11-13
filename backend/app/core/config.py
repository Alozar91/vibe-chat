"""Конфигурация бэкенда — pydantic-settings, префикс APP_* (Docs/concept.md §13)."""

from functools import lru_cache

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

    # Звонки (LiveKit, §17): пустой api_key/secret — звонки выключены (503 на /calls/token)
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_ws_url: str = "ws://localhost:7880"  # публичный адрес WS-сигналинга для клиентов
    call_ring_timeout_seconds: int = 45  # ringing дольше — ended (cleanup, §17)


@lru_cache
def get_settings() -> Settings:
    return Settings()
