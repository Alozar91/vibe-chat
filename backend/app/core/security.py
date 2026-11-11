"""Валидация JWT Keycloak: JWKS, iss/aud/exp (Docs/concept.md §5).

Бэкенд не выдаёт токены — только валидирует. Исключение — mat_-токены mini-apps (§11), не здесь.
"""

import time
from typing import Annotated, Any

import jwt
from app.core.config import get_settings
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

settings = get_settings()
security = HTTPBearer(auto_error=False)

_jwks_client = PyJWKClient(
    f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/certs",
    cache_keys=True,
    lifespan=300,
)

_ISSUER = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
_AUDIENCE = settings.keycloak_audience


class AuthContext:
    """Аутентифицированный пользователь (человек) из JWT."""

    def __init__(self, claims: dict[str, Any]) -> None:
        self.claims = claims
        self.sub: str = claims["sub"]
        self.preferred_username: str = claims.get("preferred_username", f"user-{self.sub[:8]}")
        self.is_platform_admin: bool = bool(claims.get("is_platform_admin", False))

    def __repr__(self) -> str:  # pragma: no cover
        return f"AuthContext(sub={self.sub!r})"


def validate_jwt(token: str) -> dict[str, Any]:
    """Валидация подписи (JWKS) + iss/aud/exp. Бросает jwt.PyJWTError / HTTPException 401."""
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=_AUDIENCE,
            issuer=_ISSUER,
            leeway=5,
        )
    except jwt.ExpiredSignatureError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired") from e
    except jwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from e


async def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> AuthContext:
    """Зависимость FastAPI: Bearer JWT → AuthContext."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    claims = validate_jwt(credentials.credentials)
    return AuthContext(claims)


type AuthDep = Annotated[AuthContext, Depends(require_auth)]


def now_ts() -> float:
    return time.time()
