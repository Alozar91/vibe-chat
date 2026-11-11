"""Realtime: WS-события, tickets, read receipts, бот-fanout (Docs/concept.md §9, §10, §12).

Client→server по WS — только `typing`; все мутации через REST. Fanout —
Valkey Pub/Sub (каналы chat:{id} и user:{id}). WS auth — одноразовые
tickets (атомарное удаление GETDEL). Ботам события доставляются в их
персональные Valkey Streams: только message.new/edited/deleted (§10).
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core import valkey
from app.models.bot import BotProfile
from app.models.chat import Chat, ChatMember
from app.models.message import Message
from app.models.user import User
from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

TICKET_TTL_SECONDS = 30


async def create_ws_ticket(user_id: str) -> str:
    """Одноразовый ticket на подключение; TTL 30 сек; значение — user_id (§5)."""
    ticket = uuid4().hex
    await valkey.get_valkey().set(f"ws_ticket:{ticket}", user_id, ex=TICKET_TTL_SECONDS)
    return ticket


async def consume_ws_ticket(ticket: str) -> str | None:
    """Атомарное одноразовое потребление (GETDEL); повторное использование — нет."""
    user_id = await valkey.get_valkey().getdel(f"ws_ticket:{ticket}")
    if user_id is None:
        return None
    return str(user_id)


def envelope(event_type: str, data: dict[str, Any]) -> str:
    """JSON-конверт события (§9): {type, data, event_id, ts}."""
    return json.dumps(
        {
            "type": event_type,
            "data": data,
            "event_id": str(uuid4()),
            "ts": datetime.now(UTC).timestamp(),
        },
        ensure_ascii=False,
    )


async def publish_to_chat(chat_id: str, event_type: str, data: dict[str, Any]) -> None:
    await valkey.publish(f"chat:{chat_id}", envelope(event_type, data))


async def publish_to_user(user_id: str, event_type: str, data: dict[str, Any]) -> None:
    await valkey.publish(f"user:{user_id}", envelope(event_type, data))


async def publish_message_new(db: AsyncSession, message: Message) -> None:
    """message.new участникам (Pub/Sub) + ботам чата (Streams, §10).

    Payload — полная сериализация тем же serializer'ом, что REST (§9, этап 10.2):
    клиент мержит событие в кэш по id без догоняющего REST-запроса. Ботам тот же
    payload кладётся в Stream плоским словарём (без обёртки {message: ...}).
    """
    data = await serialize_message_payload(db, message)
    await publish_message_to_members(db, message.chat_id, "message.new", data)
    await fanout_to_bots(db, message.chat_id, "message.new", data)


async def publish_message_edited(db: AsyncSession, message: Message) -> None:
    data = await serialize_message_payload(db, message)
    await publish_message_to_members(db, message.chat_id, "message.edited", data)
    await fanout_to_bots(db, message.chat_id, "message.edited", data)


async def publish_message_deleted(db: AsyncSession, message: Message) -> None:
    data = await serialize_message_payload(db, message)
    await publish_message_to_members(db, message.chat_id, "message.deleted", data)
    await fanout_to_bots(db, message.chat_id, "message.deleted", data)


async def serialize_message_payload(db: AsyncSession, message: Message) -> dict[str, Any]:
    """Полный MessageOut-словарь для WS (§9, этап 10.2): attachments с URL + реакции.

    Вызывается после commit; db.refresh поднимает атрибуты, expired при commit.
    """
    from app.services.messages import load_attachments, serialize_message
    from app.services.reactions import list_reactions

    await db.refresh(message)
    attachments = await load_attachments(db, [message.id])
    reactions = await list_reactions(db, [message.id])
    return serialize_message(message, attachments.get(message.id, []), reactions.get(message.id, []))


async def publish_message_to_members(
    db: AsyncSession, chat_id: str, event_type: str, data: dict[str, Any]
) -> None:
    """message.* → канал чата + персональные каналы участников (§9, этап 10.2).

    Людям payload оборачивается: {message: <MessageOut>} (§9). Персональные
    каналы обязательны: подписки WS на чаты фиксируются при коннекте, чат мог
    появиться позже — без user:{id} доставка не доходит. Ботам кладётся плоский
    словарь (fanout_to_bots получает data без обёртки, §10).
    """
    wrapped = {"message": data}
    await publish_to_chat(chat_id, event_type, wrapped)
    for user_id in await chat_member_ids(db, chat_id):
        await publish_to_user(user_id, event_type, wrapped)


async def publish_chat_created(db: AsyncSession, chat_id: str) -> None:
    """chat.created участникам нового чата (§9): список чатов обновится без refresh."""
    await publish_chat_event(db, chat_id, "chat.created", {})


async def publish_chat_deleted(db: AsyncSession, chat_id: str) -> None:
    """chat.updated с deleted:true участникам при soft delete чата (§9)."""
    await publish_chat_event(db, chat_id, "chat.updated", {"deleted": True})


async def publish_chat_event(db: AsyncSession, chat_id: str, event_type: str, extra: dict[str, Any]) -> None:
    """chat.* → персональные каналы участников: {chat: ChatOut} (+ extra).

    Только в user:{id} — получатель может ещё не иметь чата в подписках WS.
    """
    chat = await db.get(Chat, chat_id)
    if chat is None:
        return
    payload = {"chat": chat_out_dict(chat), **extra}
    for user_id in await chat_member_ids(db, chat_id):
        await publish_to_user(user_id, event_type, payload)


def chat_out_dict(chat: Chat) -> dict[str, Any]:
    """Словарь ChatOut для WS-событий (поля — как REST ChatOut, этап 10.2)."""
    return {
        "id": chat.id,
        "type": chat.type,
        "title": chat.title,
        "last_message_at": None,
        "unread_count": 0,
        "avatar_file_id": chat.avatar_file_id,
        "created_by": chat.created_by,
        "created_at": chat.created_at.isoformat() if chat.created_at else None,
        "deleted_at": chat.deleted_at.isoformat() if chat.deleted_at else None,
    }


async def fanout_to_bots(
    db: AsyncSession, chat_id: str, event_type: str, data: dict[str, Any]
) -> None:
    """Доставка события ботам-участникам чата в их Stream (§10).

    Presence/typing ботам не доставляются — только message.*.
    """
    from app.services.bots import push_bot_event

    bot_ids = (
        (
            await db.execute(
                select(User.id)
                .join(ChatMember, ChatMember.user_id == User.id)
                .join(BotProfile, BotProfile.user_id == User.id)
                .where(ChatMember.chat_id == chat_id, User.is_bot.is_(True))
            )
        )
        .scalars()
        .all()
    )
    for bot_id in bot_ids:
        await push_bot_event(bot_id, event_type, data)


async def chat_member_ids(db: AsyncSession, chat_id: str) -> list[str]:
    stmt = select(ChatMember.user_id).where(ChatMember.chat_id == chat_id)
    return list((await db.scalars(stmt)).all())


async def mark_read(db: AsyncSession, *, chat_id: str, user_id: str, message_id: str) -> None:
    """POST /chats/{id}/read: курсор двигается только вперёд — MAX (§12).

    Сообщение должно принадлежать чату; неучастник — 403 (через require_member).
    """
    from app.services.chats import require_member

    await require_member(db, chat_id, user_id)
    msg = await db.get(Message, message_id)
    if msg is None or msg.chat_id != chat_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "message not in this chat")

    current = await db.scalar(
        select(ChatMember.last_read_message_id).where(
            ChatMember.chat_id == chat_id, ChatMember.user_id == user_id
        )
    )
    if current is not None and current >= message_id:
        return  # курсор не откатывается (§12)

    now = datetime.now(UTC)
    await db.execute(
        update(ChatMember)
        .where(ChatMember.chat_id == chat_id, ChatMember.user_id == user_id)
        .values(last_read_message_id=message_id, last_read_at=now)
    )
    await db.commit()
    await publish_to_chat(
        chat_id,
        "read",
        {"chat_id": chat_id, "user_id": user_id, "last_read_message_id": message_id},
    )
