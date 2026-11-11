"""Валидация JWT Keycloak: JWKS, iss/aud/exp (Docs/concept.md §5).

Бэкенд не выдаёт токены — только валидирует. Единственное исключение —
mat_-токены mini-apps (§11): opaque, сессия в Valkey, распознаются здесь.
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

MAT_PREFIX = "mat_"


class AuthContext:
    """Аутентифицированный доступ: JWT Keycloak (человек) или mat_-сессия (mini-app, §11)."""

    def __init__(self, claims: dict[str, Any]) -> None:
        self.claims = claims
        self.sub: str = claims["sub"]
        self.preferred_username: str = claims.get("preferred_username", f"user-{self.sub[:8]}")
        self.is_platform_admin: bool = bool(claims.get("is_platform_admin", False))
        # mat_-сессия (§11): заполнена только при handoff-токене mini-app
        self.mat_user_id: str | None = None
        self.mat_bot_id: str | None = None

    @property
    def is_miniapp(self) -> bool:
        return self.mat_user_id is not None

    def __repr__(self) -> str:  # pragma: no cover
        return f"AuthContext(sub={self.sub!r}, miniapp={self.is_miniapp})"


class MatContext:
    """Результат resolve mat_-токена: от имени кого и внутри какого miniapp (§11)."""

    def __init__(self, user_id: str, bot_id: str) -> None:
        self.user_id = user_id
        self.bot_id = bot_id


async def _resolve_mat(credentials_token: str) -> AuthContext | None:
    """mat_-токен → AuthContext с mat-полями; не найден/истёк → None (→ 401)."""
    from app.services.miniapps import MAT_PREFIX, resolve_mat_token

    if not credentials_token.startswith(MAT_PREFIX):
        return None
    session = await resolve_mat_token(credentials_token)
    if session is None:
        return None
    ctx = AuthContext(claims={"sub": session["user_id"], "preferred_username": "miniapp"})
    ctx.mat_user_id = str(session["user_id"])
    ctx.mat_bot_id = str(session["bot_id"])
    return ctx


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
    """Зависимость FastAPI: Bearer JWT → AuthContext; mat_-токен → mat-сессия (§11).

    mat_-токен, которого нет в Valkey (истёк 15-минутный TTL) — 401 сразу.
    """
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    mat_ctx = await _resolve_mat(credentials.credentials)
    if mat_ctx is not None:
        return mat_ctx
    claims = validate_jwt(credentials.credentials)
    return AuthContext(claims)


type AuthDep = Annotated[AuthContext, Depends(require_auth)]


def now_ts() -> float:
    return time.time()
