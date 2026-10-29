import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.core.errors import unauthorized, upstream

_admin_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0}


def _base_url() -> str:
    return get_settings().keycloak_base_url


def _realm_url() -> str:
    return f"{_base_url()}/realms/{get_settings().keycloak_realm}"


def build_authorize_url(redirect_uri: str, state: str, nonce: str) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.keycloak_web_client_id,
        "response_type": "code",
        "scope": "openid",
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": nonce,
    }
    base = settings.keycloak_browser_url.rstrip("/")
    realm = settings.keycloak_realm
    return f"{base}/realms/{realm}/protocol/openid-connect/auth?{urlencode(params)}"


async def exchange_code(code: str, redirect_uri: str) -> dict[str, Any]:
    settings = get_settings()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": settings.keycloak_web_client_id,
        "client_secret": settings.keycloak_web_client_secret,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{_realm_url()}/protocol/openid-connect/token", data=data)
    if resp.status_code != 200:
        raise upstream("Не удалось обменять код авторизации")
    return resp.json()


async def password_grant(username: str, password: str) -> dict[str, Any]:
    settings = get_settings()
    data = {
        "grant_type": "password",
        "client_id": settings.keycloak_web_client_id,
        "client_secret": settings.keycloak_web_client_secret,
        "scope": "openid",
        "username": username,
        "password": password,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{_realm_url()}/protocol/openid-connect/token", data=data)
    if resp.status_code in (400, 401):
        try:
            description = str(resp.json().get("error_description") or "")
        except ValueError:
            description = ""
        raise unauthorized(description or "Неверный логин или пароль")
    if resp.status_code != 200:
        raise upstream("Keycloak недоступен")
    return resp.json()


async def revoke_refresh_token(refresh_token: str) -> None:
    settings = get_settings()
    data = {
        "client_id": settings.keycloak_web_client_id,
        "client_secret": settings.keycloak_web_client_secret,
        "refresh_token": refresh_token,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(f"{_realm_url()}/protocol/openid-connect/logout", data=data)
    except httpx.HTTPError:
        pass


async def _admin_token() -> str:
    settings = get_settings()
    now = time.time()
    if _admin_token_cache["access_token"] and now < _admin_token_cache["expires_at"] - 30:
        return str(_admin_token_cache["access_token"])
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.keycloak_backend_client_id,
        "client_secret": settings.keycloak_backend_client_secret,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{_realm_url()}/protocol/openid-connect/token", data=data)
    if resp.status_code != 200:
        raise upstream("Keycloak: не удалось получить service-account токен")
    payload = resp.json()
    _admin_token_cache["access_token"] = payload["access_token"]
    _admin_token_cache["expires_at"] = now + float(payload.get("expires_in", 60))
    return str(_admin_token_cache["access_token"])


class KeycloakAdmin:
    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {await _admin_token()}"}
        async with httpx.AsyncClient(timeout=15) as client:
            return await client.request(
                method, f"{_base_url()}/admin/realms/{get_settings().keycloak_realm}{path}", headers=headers, **kwargs
            )

    async def create_user(
        self, username: str, email: str | None, full_name: str, temp_password: str
    ) -> str:
        parts = full_name.split(" ", 1)
        body: dict[str, Any] = {
            "username": username,
            "enabled": True,
            "firstName": parts[0] or username,
            "lastName": parts[1] if len(parts) > 1 else "",
            "requiredActions": ["UPDATE_PASSWORD"],
            "credentials": [{"type": "password", "value": temp_password, "temporary": True}],
        }
        if email:
            body["email"] = email
        resp = await self._request("POST", "/users", json=body)
        if resp.status_code != 201:
            raise upstream(f"Keycloak: не удалось создать пользователя (HTTP {resp.status_code})")
        location = resp.headers.get("Location", "")
        return location.rstrip("/").split("/")[-1]

    async def set_password(self, user_id: str, temp_password: str, temporary: bool = True) -> None:
        resp = await self._request(
            "PUT",
            f"/users/{user_id}/reset-password",
            json={"type": "password", "value": temp_password, "temporary": temporary},
        )
        if resp.status_code not in (200, 204):
            raise upstream(f"Keycloak: не удалось задать пароль (HTTP {resp.status_code})")

    async def execute_actions_email(self, user_id: str, actions: list[str]) -> None:
        params = {"client_id": get_settings().keycloak_web_client_id}
        resp = await self._request(
            "POST", f"/users/{user_id}/execute-actions-email", params=params, json=actions
        )
        if resp.status_code != 204:
            raise upstream(f"Keycloak: не удалось отправить письмо (HTTP {resp.status_code})")

    async def set_enabled(self, user_id: str, enabled: bool) -> None:
        resp = await self._request("PUT", f"/users/{user_id}", json={"enabled": enabled})
        if resp.status_code not in (200, 204, 404):
            raise upstream(f"Keycloak: не удалось изменить статус (HTTP {resp.status_code})")

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        resp = await self._request("GET", f"/users/{user_id}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise upstream(f"Keycloak: не удалось получить пользователя (HTTP {resp.status_code})")
        return resp.json()

    async def list_users(self, first: int = 0, max_results: int = 100) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/users", params={"first": first, "max": max_results})
        if resp.status_code != 200:
            raise upstream(f"Keycloak: не удалось получить список пользователей (HTTP {resp.status_code})")
        return resp.json()
