from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from valkey.asyncio import Valkey

from app.config import get_settings
from app.core.errors import not_found
from app.core.ratelimit import check_limit
from app.core.security import AuthContext
from app.core.valkey import get_valkey
from app.db.session import get_session
from app.modules.auth import service as auth_service
from app.modules.auth import sessions
from app.modules.auth.dependencies import get_auth_context, require_csrf
from app.modules.users.service import serialize_user

router = APIRouter(prefix="/v1/auth", tags=["auth"])

OPEN_ROUTES = {"login", "callback", "direct-login"}


class DirectLoginPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _session_response(response: Response, sid: str, csrf: str) -> Response:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        sid,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    return response


@router.post("/direct-login")
async def direct_login(
    request: Request,
    payload: DirectLoginPayload,
    db: AsyncSession = Depends(get_session),
    valkey: Valkey = Depends(get_valkey),
) -> Response:
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    await check_limit(valkey, "login", ip or "unknown", 10, 60)
    sid, csrf, user = await auth_service.direct_login(
        db, valkey, payload.username.strip(), payload.password, ip, user_agent
    )
    response = JSONResponse(serialize_user(user, include_contacts=True))
    return _session_response(response, sid, csrf)


@router.get("/login")
async def login(
    request: Request,
    origin: str | None = None,
    valkey: Valkey = Depends(get_valkey),
) -> Response:
    settings = get_settings()
    allowed = settings.allowed_origin_list
    origin_value = origin if origin in allowed else settings.public_base_url
    redirect = await auth_service.build_login_redirect(valkey, origin_value)
    return Response(status_code=302, headers={"Location": redirect})


@router.get("/callback")
async def callback(
    request: Request,
    code: str,
    state: str,
    db: AsyncSession = Depends(get_session),
    valkey: Valkey = Depends(get_valkey),
) -> Response:
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    sid, csrf, origin = await auth_service.complete_login(db, valkey, code, state, ip, user_agent)
    settings = get_settings()
    response = Response(status_code=302, headers={"Location": origin or settings.public_base_url})
    return _session_response(response, sid, csrf)


@router.post("/logout", dependencies=[Depends(require_csrf)])
async def logout(
    ctx: AuthContext = Depends(get_auth_context),
    valkey: Valkey = Depends(get_valkey),
) -> Response:
    if ctx.session_id:
        await auth_service.logout_current(valkey, ctx.session_id)
    response = Response(status_code=204)
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return response


@router.post("/logout-all", dependencies=[Depends(require_csrf)])
async def logout_all(
    ctx: AuthContext = Depends(get_auth_context),
    valkey: Valkey = Depends(get_valkey),
) -> Response:
    count = await sessions.revoke_all(valkey, ctx.user_id)
    response = Response(status_code=204, content=None)
    response.headers["X-Revoked-Sessions"] = str(count)
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return response


@router.get("/sessions")
async def list_sessions(
    ctx: AuthContext = Depends(get_auth_context),
    valkey: Valkey = Depends(get_valkey),
) -> dict:
    items = await sessions.list_sessions(valkey, ctx.user_id, ctx.session_id)
    return {"items": items}


@router.delete("/sessions/{session_id}", dependencies=[Depends(require_csrf)])
async def delete_session(
    session_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    valkey: Valkey = Depends(get_valkey),
) -> Response:
    raw = await valkey.get("sess:" + session_id)
    if raw is None:
        raise not_found("Сессия")
    if not await sessions.revoke_session(valkey, session_id):
        raise not_found("Сессия")
    return Response(status_code=204)
