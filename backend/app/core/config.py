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

    # Файлы
    presign_ttl_seconds: int = 3600
    file_pending_ttl_hours: int = 24
    file_orphan_days: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
