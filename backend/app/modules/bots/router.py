import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import bad_request
from app.core.security import AuthContext
from app.db.session import get_session
from app.modules.auth.dependencies import get_auth_context, require_csrf
from app.modules.bots import service as bots_service

router = APIRouter(prefix="/v1/bots", tags=["bots"], dependencies=[Depends(require_csrf)])


class BotCreate(BaseModel):
    model_config = {"extra": "forbid"}

    username: str
    full_name: str = ""
    description: str | None = None


class BotUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    description: str | None = None
    webhook_url: str | None = None
    is_enabled: bool | None = None


class TokenCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = "token"
    expires_at: str | None = None


class CommandsSet(BaseModel):
    model_config = {"extra": "forbid"}

    commands: list[dict] = Field(default_factory=list)


def _bot_id(bot_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(bot_id)
    except ValueError as exc:
        raise bad_request("bot_id: некорректный UUID") from exc


def _dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise bad_request("expires_at: ISO 8601") from exc


@router.post("")
async def create_bot(
    payload: BotCreate,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    from app.core.audit import log_action

    await bots_service.require_org_admin(ctx.role)
    bot, token = await bots_service.create_bot(
        db, ctx.user_id, payload.username, payload.full_name, payload.description
    )
    await log_action(db, actor_id=ctx.user_id, action="bot.created", entity_type="bot", entity_id=bot["user_id"])
    await db.commit()
    return {**bot, "token": token}


@router.get("")
async def list_bots(
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    from sqlalchemy import select

    from app.models import Bot, User

    await bots_service.require_org_admin(ctx.role)
    rows = (
        await db.execute(
            select(Bot, User)
            .join(User, User.id == Bot.user_id)
            .where(User.is_deleted.is_(False))
            .order_by(Bot.created_at)
        )
    ).all()
    return {"items": [bots_service.serialize_bot(bot, user) for bot, user in rows]}


@router.get("/me")
async def bot_me(
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    if ctx.kind != "bot":
        raise bad_request("Эндпоинт только для ботов")
    bot, user = await bots_service.get_bot_or_404(db, ctx.user_id)
    return bots_service.serialize_bot(bot, user)


@router.get("/getUpdates")
async def get_updates(
    timeout: int = Query(default=30, ge=0, le=60),
    offset: int = Query(default=0, ge=0),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    import asyncio

    if ctx.kind != "bot":
        raise bad_request("Эндпоинт только для ботов")
    deadline = asyncio.get_event_loop().time() + timeout
    last_offset = offset
    while True:
        updates = await bots_service.fetch_updates(db, ctx.user_id, last_offset)
        if updates:
            return {"updates": updates, "next_offset": updates[-1]["update_id"]}
        if asyncio.get_event_loop().time() >= deadline:
            return {"updates": [], "next_offset": last_offset}
        await db.rollback()
        await asyncio.sleep(0.4)


@router.get("/{bot_id}")
async def get_bot(
    bot_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await bots_service.require_org_admin(ctx.role)
    bot, user = await bots_service.get_bot_or_404(db, _bot_id(bot_id))
    return bots_service.serialize_bot(bot, user)


@router.patch("/{bot_id}")
async def update_bot(
    bot_id: str,
    payload: BotUpdate,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await bots_service.require_org_admin(ctx.role)
    return await bots_service.update_bot(db, _bot_id(bot_id), payload.model_dump(exclude_none=True))


@router.delete("/{bot_id}")
async def delete_bot(
    bot_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> Response:
    from app.core.audit import log_action

    await bots_service.require_org_admin(ctx.role)
    await bots_service.delete_bot(db, _bot_id(bot_id))
    await log_action(db, actor_id=ctx.user_id, action="bot.deleted", entity_type="bot", entity_id=bot_id)
    await db.commit()
    return Response(status_code=204)


@router.post("/{bot_id}/tokens")
async def create_token(
    bot_id: str,
    payload: TokenCreate,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await bots_service.require_org_admin(ctx.role)
    return await bots_service.create_bot_token(db, _bot_id(bot_id), payload.name, _dt(payload.expires_at))


@router.get("/{bot_id}/tokens")
async def list_tokens(
    bot_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await bots_service.require_org_admin(ctx.role)
    return {"items": await bots_service.list_bot_tokens(db, _bot_id(bot_id))}


@router.delete("/{bot_id}/tokens/{token_id}")
async def revoke_token(
    bot_id: str,
    token_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> Response:
    from app.core.audit import log_action

    await bots_service.require_org_admin(ctx.role)
    await bots_service.revoke_bot_token(db, _bot_id(bot_id), uuid.UUID(token_id))
    await log_action(
        db, actor_id=ctx.user_id, action="bot.token.revoked", entity_type="bot_token", entity_id=token_id
    )
    await db.commit()
    return Response(status_code=204)


@router.post("/{bot_id}/commands")
async def set_commands(
    bot_id: str,
    payload: CommandsSet,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    await bots_service.require_org_admin(ctx.role)
    return {"items": await bots_service.set_bot_commands(db, _bot_id(bot_id), payload.commands)}
