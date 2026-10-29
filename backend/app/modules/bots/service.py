import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import bad_request, forbidden, not_found
from app.core.permissions import can_manage_bots_org
from app.core.security import generate_bot_token, sha256_hex
from app.core.timeutil import utcnow
from app.models import (
    Bot,
    BotCommand,
    BotToken,
    ChatMember,
    ChatMemberStatus,
    OutboxEvent,
    User,
    UserKind,
    UserRole,
    UserStatus,
)
from app.modules.users.service import validate_new_username


def serialize_bot(bot: Bot, user: User) -> dict[str, Any]:
    return {
        "user_id": str(bot.user_id),
        "username": user.username,
        "full_name": user.full_name,
        "description": bot.description,
        "webhook_url": bot.webhook_url,
        "is_enabled": bot.is_enabled,
        "created_by": str(bot.created_by),
        "created_at": bot.created_at.isoformat(),
    }


async def require_org_admin(ctx_role: UserRole) -> None:
    if not can_manage_bots_org(ctx_role):
        raise forbidden("Управлять ботами может владелец или админ организации")


async def get_bot_or_404(session: AsyncSession, bot_user_id: uuid.UUID) -> tuple[Bot, User]:
    row = (
        await session.execute(
            select(Bot, User).join(User, User.id == Bot.user_id).where(Bot.user_id == bot_user_id)
        )
    ).first()
    if row is None or row[1].is_deleted:
        raise not_found("Бот")
    return row[0], row[1]


async def create_bot(
    session: AsyncSession, owner_id: uuid.UUID, username: str, full_name: str, description: str | None
) -> tuple[dict[str, Any], str]:
    username = await validate_new_username(session, username)
    existing_kind_bot = (
        await session.scalars(select(User).where(User.username == username, User.kind == UserKind.BOT))
    ).one_or_none()
    if existing_kind_bot is not None:
        raise bad_request("username занят")
    token = generate_bot_token()
    user = User(
        kind=UserKind.BOT,
        keycloak_sub=None,
        username=username,
        full_name=full_name or username,
        role=UserRole.MEMBER,
        status=UserStatus.ACTIVE,
        source="bot",
    )
    session.add(user)
    await session.flush()
    bot = Bot(user_id=user.id, description=description, created_by=owner_id)
    session.add(bot)
    bot_token = BotToken(
        bot_id=user.id,
        name="default",
        token_hash=sha256_hex(token),
        token_prefix=token[:8],
        scopes=[],
    )
    session.add(bot_token)
    await session.commit()
    return serialize_bot(bot, user), token


async def update_bot(
    session: AsyncSession, bot_user_id: uuid.UUID, payload: dict[str, Any]
) -> dict[str, Any]:
    bot, user = await get_bot_or_404(session, bot_user_id)
    if "description" in payload:
        bot.description = payload.get("description")
    if "webhook_url" in payload:
        bot.webhook_url = payload.get("webhook_url")
    if "is_enabled" in payload:
        bot.is_enabled = bool(payload["is_enabled"])
    bot.updated_at = func.now()
    user.updated_at = utcnow()
    await session.commit()
    return serialize_bot(bot, user)


async def delete_bot(session: AsyncSession, bot_user_id: uuid.UUID) -> None:
    bot, user = await get_bot_or_404(session, bot_user_id)
    user.is_deleted = True
    user.updated_at = utcnow()
    await session.commit()


async def create_bot_token(
    session: AsyncSession, bot_user_id: uuid.UUID, name: str, expires_at: datetime | None
) -> dict[str, Any]:
    await get_bot_or_404(session, bot_user_id)
    token = generate_bot_token()
    record = BotToken(
        bot_id=bot_user_id,
        name=name or "token",
        token_hash=sha256_hex(token),
        token_prefix=token[:8],
        scopes=[],
        expires_at=expires_at,
    )
    session.add(record)
    await session.commit()
    return {
        "id": str(record.id),
        "token": token,
        "token_prefix": record.token_prefix,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


async def revoke_bot_token(session: AsyncSession, bot_user_id: uuid.UUID, token_id: uuid.UUID) -> None:
    record = await session.get(BotToken, token_id)
    if record is None or record.bot_id != bot_user_id:
        raise not_found("Токен")
    if record.revoked_at is not None:
        return
    record.revoked_at = utcnow()
    await session.commit()


async def list_bot_tokens(session: AsyncSession, bot_user_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(BotToken)
            .where(BotToken.bot_id == bot_user_id, BotToken.revoked_at.is_(None))
            .order_by(BotToken.created_at.desc())
        )
    ).all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "token_prefix": t.token_prefix,
            "expires_at": t.expires_at.isoformat() if t.expires_at else None,
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
            "created_at": t.created_at.isoformat(),
        }
        for t in rows
    ]


async def set_bot_commands(
    session: AsyncSession, bot_user_id: uuid.UUID, commands: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    await get_bot_or_404(session, bot_user_id)
    await session.execute(sa_delete(BotCommand).where(BotCommand.bot_id == bot_user_id))
    for item in commands[:100]:
        command = str(item.get("command") or "").strip()
        if not command.startswith("/") or " " in command or len(command) > 64:
            raise bad_request("command: '/name', до 64 символов, без пробелов")
        session.add(
            BotCommand(bot_id=bot_user_id, command=command, description=item.get("description"))
        )
    await session.commit()
    return await get_bot_commands(session, bot_user_id)


async def get_bot_commands(session: AsyncSession, bot_user_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(BotCommand).where(BotCommand.bot_id == bot_user_id).order_by(BotCommand.command)
        )
    ).all()
    return [
        {"command": c.command, "description": c.description}
        for c in rows
    ]


async def bot_chat_ids(session: AsyncSession, bot_user_id: uuid.UUID) -> set[uuid.UUID]:
    return set(
        (
            await session.scalars(
                select(ChatMember.chat_id).where(
                    ChatMember.user_id == bot_user_id,
                    ChatMember.status == ChatMemberStatus.ACTIVE,
                )
            )
        ).all()
    )


BOT_EVENT_TYPES = (
    "message.created",
    "message.updated",
    "message.deleted",
    "message.command",
    "chat.member.joined",
    "chat.member.left",
    "bot.added_to_chat",
    "bot.removed_from_chat",
)


async def fetch_updates(
    session: AsyncSession, bot_user_id: uuid.UUID, offset: int, limit: int = 100
) -> list[dict[str, Any]]:
    chat_ids = await bot_chat_ids(session, bot_user_id)
    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.seq > offset,
            OutboxEvent.event_type.in_(BOT_EVENT_TYPES),
            (OutboxEvent.chat_id.is_(None) if not chat_ids else OutboxEvent.chat_id.in_(chat_ids)),
        )
        .order_by(OutboxEvent.seq)
        .limit(limit)
    )
    rows = (await session.scalars(stmt)).all()
    return [
        {"update_id": ev.seq, "type": ev.event_type, "chat_id": str(ev.chat_id) if ev.chat_id else None, "payload": ev.payload}
        for ev in rows
    ]
