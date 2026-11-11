"""Realtime: WS-события, tickets, read receipts (Docs/concept.md §9, §12).

Client→server по WS — только `typing`; все мутации через REST. Fanout —
Valkey Pub/Sub (каналы chat:{id} и user:{id}). WS auth — одноразовые
tickets (атомарное удаление GETDEL).
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core import valkey
from app.models.chat import ChatMember
from app.models.message import Message
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
    """message.new участникам чата (сериализация с URL — в роуте; здесь — ядро)."""
    data: dict[str, Any] = {
        "id": message.id,
        "chat_id": message.chat_id,
        "sender_id": message.sender_id,
        "type": message.type,
        "text": message.text,
        "client_ref": message.client_ref,
        "reply_to_id": message.reply_to_id,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }
    await publish_to_chat(message.chat_id, "message.new", data)


async def publish_message_edited(message: Message) -> None:
    await publish_to_chat(
        message.chat_id,
        "message.edited",
        {"id": message.id, "chat_id": message.chat_id, "text": message.text, "edited_at": _iso(message.edited_at)},
    )


async def publish_message_deleted(message: Message) -> None:
    await publish_to_chat(
        message.chat_id,
        "message.deleted",
        {"id": message.id, "chat_id": message.chat_id, "deleted_at": _iso(message.deleted_at)},
    )


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


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
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "message not in this chat")

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
