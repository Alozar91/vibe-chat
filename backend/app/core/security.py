import base64
import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import jwt
from jwt import PyJWK

from app.config import get_settings
from app.core.errors import unauthorized
from app.models import UserKind, UserRole, UserStatus


@dataclass
class AuthContext:
    user_id: uuid.UUID
    kind: UserKind
    role: UserRole
    status: UserStatus
    via: str
    session_id: str | None = None
    csrf_token: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)


class JWKSCache:
    def __init__(self) -> None:
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at: float = 0.0

    async def _fetch(self) -> None:
        import httpx

        settings = get_settings()
        url = f"{settings.keycloak_base_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/certs"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        jwks = resp.json()
        self._keys = {}
        for k in jwks.get("keys", []):
            if k.get("use") not in (None, "sig") or k.get("alg") not in (None, "RS256"):
                continue
            try:
                self._keys[k["kid"]] = PyJWK.from_dict(k)
            except jwt.PyJWTError:
                continue
        self._fetched_at = time.time()

    async def get_key(self, kid: str | None) -> PyJWK:
        stale = (time.time() - self._fetched_at) > get_settings().jwks_cache_ttl_seconds
        if kid not in self._keys or stale:
            await self._fetch()
        if kid is None or kid not in self._keys:
            raise unauthorized("Неизвестный ключ подписи токена")
        return self._keys[kid]


jwks_cache = JWKSCache()


async def verify_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        header = jwt.get_unverified_header(token)
        key = await jwks_cache.get_key(header.get("kid"))
        claims: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=settings.keycloak_api_audience,
            issuer=settings.issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise unauthorized(f"Некорректный токен: {exc}") from exc
    return claims


def verify_id_token_unverified(token: str) -> dict[str, Any]:
    return jwt.decode(token, options={"verify_signature": False})


async def verify_id_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        header = jwt.get_unverified_header(token)
        key = await jwks_cache.get_key(header.get("kid"))
        claims: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=settings.keycloak_web_client_id,
            issuer=settings.issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise unauthorized(f"Некорректный id_token: {exc}") from exc
    return claims


def generate_session_id() -> str:
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def generate_bot_token() -> str:
    return f"mt_{secrets.token_urlsafe(32)}"


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def generate_invite_code() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip("=")


def encode_state(nonce: str, origin: str) -> str:
    raw = json.dumps({"n": nonce, "o": origin})
    return secrets.token_urlsafe(32) + "." + base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_state(state: str) -> tuple[str, str]:
    try:
        marker, encoded = state.split(".", 1)
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        data = json.loads(raw)
        return data["n"], data["o"]
    except Exception as exc:
        raise unauthorized("Некорректный state") from exc
