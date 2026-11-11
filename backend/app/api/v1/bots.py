"""Боты: REST-роуты — управление (/bots, JWT платформенного админа) и Bot API (/bot/*, vbt_) (§10, §12)."""

from typing import Annotated, Any

from app.api.deps import UserDep
from app.db.session import get_db
from app.models.user import User
from app.schemas.bot import (
    BotCreatedOut,
    BotCreateIn,
    BotMessageIn,
    BotOut,
    BotUpdateIn,
    BotUpdatesOut,
)
from app.schemas.message import MessageOut
from app.services import bots as bot_service
from app.services import chats as chat_service
from app.services import messages as message_service
from app.services import reactions as reaction_service
from app.services import realtime as rt
from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

admin_router = APIRouter(tags=["bots"])
bot_router = APIRouter(tags=["bot-api"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


def _bot_out(user: User, description: str | None, miniapp_url: str | None, miniapp_name: str | None) -> BotOut:
    return BotOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        description=description,
        is_active=user.is_active,
        miniapp_url=miniapp_url,
        miniapp_name=miniapp_name,
        created_at=user.created_at,
    )


# --- Управление ботами (JWT, платформенный админ, §12) ---


@admin_router.get("/bots", response_model=list[BotOut])
async def list_bots(me: UserDep, db: DbDep) -> list[BotOut]:
    await bot_service.require_platform_admin(me)
    rows = await bot_service.list_bots(db)
    return [
        _bot_out(user, profile.description, profile.miniapp_url, profile.miniapp_name)
        for user, profile in rows
    ]


@admin_router.post("/bots", response_model=BotCreatedOut, status_code=201)
async def create_bot(body: BotCreateIn, me: UserDep, db: DbDep) -> BotCreatedOut:
    bot_user, profile, token = await bot_service.create_bot(
        db,
        admin=me,
        username=body.username,
        display_name=body.display_name,
        description=body.description,
    )
    out = _bot_out(bot_user, profile.description, profile.miniapp_url, profile.miniapp_name)
    return BotCreatedOut(**out.model_dump(), token=token)


@admin_router.post("/bots/{bot_id}/token/regenerate", response_model=dict[str, str])
async def regenerate_token(bot_id: str, me: UserDep, db: DbDep) -> dict[str, str]:
    """Старый токен отклоняется сразу; зависший long polling завершается (§10)."""
    token = await bot_service.regenerate_token(db, admin=me, bot_id=bot_id)
    return {"token": token}


@admin_router.patch("/bots/{bot_id}", response_model=BotOut)
async def update_bot(bot_id: str, body: BotUpdateIn, me: UserDep, db: DbDep) -> BotOut:
    bot_user, profile = await bot_service.update_bot(
        db,
        admin=me,
        bot_id=bot_id,
        description=body.description,
        is_active=body.is_active,
        miniapp_url=body.miniapp_url,
        miniapp_name=body.miniapp_name,
        description_set=body.description is not None,
        miniapp_set=body.miniapp_url is not None or body.miniapp_name is not None,
    )
    return _bot_out(bot_user, profile.description, profile.miniapp_url, profile.miniapp_name)


# --- Bot API (Bearer vbt_, §12) ---


async def bot_dep(
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
) -> tuple[User, Any]:
    return await bot_service.authenticate_bot(db, authorization)


BotDep = Annotated[tuple[User, Any], Depends(bot_dep)]


@bot_router.get("/bot/me", response_model=BotOut)
async def bot_me(bot: BotDep) -> BotOut:
    user, profile = bot
    return _bot_out(user, profile.description, profile.miniapp_url, profile.miniapp_name)


@bot_router.get("/bot/chats")
async def bot_chats(bot: BotDep, db: DbDep) -> list[dict[str, Any]]:
    user, _profile = bot
    chats = await chat_service.list_user_chats(db, user.id)
    return [{"id": c.id, "type": c.type, "title": c.title, "created_at": c.created_at.isoformat()} for c in chats]


@bot_router.get("/bot/chats/{chat_id}/messages", response_model=list[MessageOut])
async def bot_chat_messages(
    chat_id: str,
    bot: BotDep,
    db: DbDep,
    before: str | None = None,
    after: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[MessageOut]:
    """История + основа resync (§10). Membership бота проверяется как у людей."""
    user, _profile = bot
    messages = await message_service.list_messages(
        db, chat_id=chat_id, user_id=user.id, before=before, after=after, limit=limit
    )
    attachments = await message_service.load_attachments(db, [m.id for m in messages])
    reactions = await reaction_service.list_reactions(db, [m.id for m in messages])
    return [
        MessageOut.model_validate(
            message_service.serialize_message(
                m, attachments.get(m.id, []), reactions.get(m.id, [])
            )
        )
        for m in messages
    ]


@bot_router.post("/bot/messages", response_model=MessageOut, status_code=201)
async def bot_send_message(body: BotMessageIn, bot: BotDep, db: DbDep) -> MessageOut:
    """Отправка: текст/фото/файл, reply; идемпотентность Idempotency-Key/client_ref (§10)."""
    user, _profile = bot
    message, _created = await message_service.create_message(
        db,
        sender=user,
        chat_id=body.chat_id,
        text=body.text,
        attachments=[a.model_dump() for a in body.attachments],
        reply_to_id=body.reply_to_id,
        timezone_name=None,  # у ботов timezone NULL (§6)
        client_ref=body.client_ref,
    )
    attachments = await message_service.load_attachments(db, [message.id])
    await rt.publish_message_new(db, message)
    return MessageOut.model_validate(
        message_service.serialize_message(message, attachments.get(message.id, []))
    )


@bot_router.get("/bot/updates", response_model=BotUpdatesOut)
async def bot_updates(
    bot: BotDep,
    db: DbDep,
    offset: str | None = None,
    timeout: int = Query(default=30, ge=0, le=60),
) -> BotUpdatesOut:
    """Long polling: offset = Stream ID; отставание → resync: true (§10)."""
    user, _profile = bot
    # деактивация уже проверена в authenticate_bot; зависший poll завершится на след. запросе
    result = await bot_service.read_updates(
        bot_user_id=user.id, offset=offset, timeout_seconds=timeout
    )
    return BotUpdatesOut(
        updates=result.get("updates", []),
        offset=result.get("offset"),
        resync=bool(result.get("resync", False)),
    )
