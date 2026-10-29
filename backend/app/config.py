from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8080"
    allowed_origins: str = "http://localhost:5173,http://localhost:8080"

    database_url: str = "postgresql+asyncpg://vibe:vibe@localhost:5432/vibe"
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_echo: bool = False

    valkey_url: str = "valkey://localhost:6379/0"
    session_ttl_seconds: int = 43200
    session_cookie_name: str = "vibe_session"
    csrf_cookie_name: str = "vibe_csrf"
    cookie_secure: bool = False
    user_cache_ttl_seconds: int = 30
    ws_event_channel: str = "ws:events"

    keycloak_url: str = "http://localhost:8081"
    keycloak_public_url: str = ""
    keycloak_realm: str = "messenger"
    keycloak_internal_url: str = ""
    keycloak_web_client_id: str = "messenger-web"
    keycloak_web_client_secret: str = "dev-web-secret-change-me"
    keycloak_api_audience: str = "messenger-api"
    keycloak_backend_client_id: str = "messenger-backend"
    keycloak_backend_client_secret: str = "dev-backend-secret-change-me"
    jwks_cache_ttl_seconds: int = 300
    keycloak_sync_enabled: bool = False

    s3_endpoint_url: str = "http://localhost:9000"
    s3_public_url: str = ""
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "vibe-media"
    presign_put_ttl: int = 900
    presign_get_ttl: int = 300

    bootstrap_admin_username: str = ""

    message_max_length: int = 4096
    max_file_size: int = 100 * 1024 * 1024
    max_attachments: int = 10
    max_group_members: int = 10000
    all_mention_threshold: int = 100

    outbox_retention_days: int = 7
    message_retention_days: int = 0

    push_include_body: bool = True
    push_large_chat_threshold: int = 200
    fcm_credentials_path: str = ""
    apns_key_path: str = ""
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_topic: str = ""
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    webpush_subject: str = "mailto:admin@corp.local"
    clamav_host: str = ""
    clamav_port: int = 3310

    @property
    def keycloak_base_url(self) -> str:
        return self.keycloak_internal_url or self.keycloak_url

    @property
    def keycloak_browser_url(self) -> str:
        return self.keycloak_public_url or self.keycloak_url

    @property
    def issuer(self) -> str:
        return f"{self.keycloak_browser_url.rstrip('/')}/realms/{self.keycloak_realm}"

    @property
    def allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
