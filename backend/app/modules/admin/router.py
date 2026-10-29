import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from valkey.asyncio import Valkey

from app.core.errors import bad_request
from app.core.security import AuthContext
from app.core.valkey import get_valkey
from app.db.session import get_session
from app.models import Bot
from app.modules.admin import service as admin_service
from app.modules.auth.dependencies import get_auth_context, require_csrf

router = APIRouter(prefix="/v1/admin", tags=["admin"], dependencies=[Depends(require_csrf)])


class UserCreate(BaseModel):
    model_config = {"extra": "forbid"}

    username: str
    full_name: str
    email: str | None = None
    send_email: bool = True


class ResetPassword(BaseModel):
    model_config = {"extra": "forbid"}

    send_email: bool = True


def _uid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise bad_request("Некорректный UUID") from exc


def _require_admin(ctx: AuthContext) -> None:
    if ctx.role not in ("owner", "admin"):
        raise bad_request("Недостаточно прав")


@router.get("/users")
async def list_users(
    limit: int | None = Query(default=None, ge=1, le=100),
    offset: int | None = Query(default=None, ge=0),
    q: str | None = Query(default=None, max_length=100),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    _require_admin(ctx)
    return await admin_service.list_users(db, limit or 50, offset or 0, q)


@router.post("/users")
async def create_user(
    payload: UserCreate,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
    valkey: Valkey = Depends(get_valkey),
) -> dict:
    _require_admin(ctx)
    actor = await admin_service.require_actor(db, ctx.user_id)
    ip = request.client.host if request.client else None
    return await admin_service.create_user(
        db, valkey, actor, payload.username, payload.full_name, payload.email, payload.send_email, ip
    )


@router.post("/users/import")
async def import_users(
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
    valkey: Valkey = Depends(get_valkey),
) -> dict:
    _require_admin(ctx)
    actor = await admin_service.require_actor(db, ctx.user_id)
    form = await request.form()
    upload = form.get("file")
    if upload is None or isinstance(upload, str) or not hasattr(upload, "read"):
        raise bad_request("Ожидается multipart-поле file с CSV")
    content = (await upload.read()).decode("utf-8-sig")
    ip = request.client.host if request.client else None
    return await admin_service.import_users_csv(db, valkey, actor, content, ip)


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    payload: ResetPassword,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    _require_admin(ctx)
    actor = await admin_service.require_actor(db, ctx.user_id)
    ip = request.client.host if request.client else None
    return await admin_service.reset_password(db, actor, _uid(user_id), payload.send_email, ip)


@router.post("/users/{user_id}/disable")
async def disable_user(
    user_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
    valkey: Valkey = Depends(get_valkey),
) -> dict:
    _require_admin(ctx)
    actor = await admin_service.require_actor(db, ctx.user_id)
    ip = request.client.host if request.client else None
    return await admin_service.set_user_status(db, valkey, actor, _uid(user_id), disable=True, ip=ip)


@router.post("/users/{user_id}/enable")
async def enable_user(
    user_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
    valkey: Valkey = Depends(get_valkey),
) -> dict:
    _require_admin(ctx)
    actor = await admin_service.require_actor(db, ctx.user_id)
    ip = request.client.host if request.client else None
    return await admin_service.set_user_status(db, valkey, actor, _uid(user_id), disable=False, ip=ip)


@router.get("/sessions")
async def user_sessions(
    user_id: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    valkey: Valkey = Depends(get_valkey),
) -> dict:
    _require_admin(ctx)
    from app.modules.auth.sessions import list_sessions

    if not user_id:
        raise bad_request("user_id обязателен")
    items = await list_sessions(valkey, _uid(user_id), None)
    return {"items": items}


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    valkey: Valkey = Depends(get_valkey),
) -> Response:
    _require_admin(ctx)
    from app.modules.auth.sessions import revoke_session

    await revoke_session(valkey, session_id)
    return Response(status_code=204)


@router.get("/stats")
async def stats(
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    _require_admin(ctx)
    return await admin_service.stats(db)


@router.get("/audit")
async def audit(
    limit: int | None = Query(default=None, ge=1, le=100),
    offset: int | None = Query(default=None, ge=0),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    _require_admin(ctx)
    return await admin_service.list_audit(db, limit or 50, offset or 0)


@router.get("/bots")
async def list_bots(
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    _require_admin(ctx)
    from sqlalchemy import select

    from app.models import User
    from app.modules.bots.service import serialize_bot

    rows = (
        await db.execute(
            select(Bot, User)
            .join(User, User.id == Bot.user_id)
            .where(User.is_deleted.is_(False))
            .order_by(Bot.created_at)
        )
    ).all()
    return {"items": [serialize_bot(bot, user) for bot, user in rows]}


@router.post("/bots/{bot_id}/disable")
async def disable_bot(
    bot_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    _require_admin(ctx)
    from app.core.audit import log_action
    from app.core.timeutil import utcnow

    bot = await db.get(Bot, _uid(bot_id))
    if bot is None:
        raise bad_request("Бот не найден")
    bot.is_enabled = False
    bot.updated_at = utcnow()
    await log_action(
        db,
        actor_id=ctx.user_id,
        action="bot.disabled",
        entity_type="bot",
        entity_id=bot_id,
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    return {"user_id": bot_id, "is_enabled": False}
