"""Клиент Keycloak Admin API (Docs/concept.md §5 «Регистрация»).

Используется только для создания пользователей при инвайт-регистрации:
передаются только username + password — персональные данные в KC не попадают
(§5: Keycloak — только identification/authentication).

Аутентификация: service-account client `backend-admin` (confidential),
grant client_credentials, роль realm-management/manage-users.
"""

from typing import Any

import httpx
from app.core.config import get_settings
from fastapi import HTTPException, status


class KeycloakAdminClient:
    """Минимальный клиент Admin API: token + create user. Без внешних зависимостей."""

    def __init__(self, base_url: str, realm: str, client_id: str, client_secret: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._realm = realm
        self._client_id = client_id
        self._client_secret = client_secret

    async def _token(self) -> str:
        """client_credentials grant сервис-аккаунта."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/realms/{self._realm}/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
        if resp.status_code != 200:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "keycloak admin token failed")
        data: dict[str, Any] = resp.json()
        token: str = data["access_token"]
        return token

    async def create_user(self, *, username: str, password: str) -> str:
        """Создаёт пользователя (только credentials); возвращает KC user id.

        409 (username занят в KC) → пробрасывается как status от KC;
        вызывающий сервис маппит в ответ клиенту.
        """
        token = await self._token()
        payload = {
            "username": username,
            "enabled": True,
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base_url}/admin/realms/{self._realm}/users",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
        if resp.status_code == 409:
            raise HTTPException(status.HTTP_409_CONFLICT, "username already taken")
        if resp.status_code != 201:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "keycloak user creation failed")
        location = resp.headers.get("Location", "")
        kc_id = location.rstrip("/").rsplit("/", 1)[-1] if location else ""
        if not kc_id:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "keycloak user id missing")
        return kc_id

    async def delete_user(self, kc_user_id: str) -> None:
        """Компенсация при проигрыше гонки за инвайт (§5)."""
        token = await self._token()
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{self._base_url}/admin/realms/{self._realm}/users/{kc_user_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code not in (204, 404):
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "keycloak rollback failed")


def get_kc_admin() -> KeycloakAdminClient:
    """Клиент из настроек; не настроен secret → 503 (регистрация выключена)."""
    settings = get_settings()
    secret = settings.keycloak_admin_client_secret
    if not secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "registration is not configured",
        )
    return KeycloakAdminClient(
        base_url=settings.keycloak_url,
        realm=settings.keycloak_realm,
        client_id=settings.keycloak_admin_client_id,
        client_secret=secret,
    )
