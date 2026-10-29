import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chat, ChatMember, ChatMemberStatus, Message, User


async def search_messages(
    session: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    chat_id: uuid.UUID | None,
    author_id: uuid.UUID | None,
    date_from=None,
    date_to=None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    ts_query = func.websearch_to_tsquery("russian", query)
    conditions: list[Any] = [
        Message.deleted_at.is_(None),
        Message.search_vector.op("@@")(ts_query),
    ]
    if chat_id is not None:
        conditions.append(Message.chat_id == chat_id)
    if author_id is not None:
        conditions.append(Message.sender_id == author_id)
    if date_from is not None:
        conditions.append(Message.created_at >= date_from)
    if date_to is not None:
        conditions.append(Message.created_at <= date_to)
    membership = select(ChatMember.chat_id).where(
        ChatMember.user_id == user_id, ChatMember.status == ChatMemberStatus.ACTIVE
    )
    if chat_id is None:
        conditions.append(Message.chat_id.in_(membership))
    stmt = (
        select(Message)
        .where(*conditions)
        .order_by(Message.created_at.desc())
        .limit(limit + 1)
        .offset(offset)
    )
    rows = (await session.scalars(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        {
            "type": "message",
            "chat_id": str(m.chat_id),
            "seq": m.seq,
            "message": {
                "seq": m.seq,
                "body": m.body,
                "sender_id": str(m.sender_id),
                "created_at": m.created_at.isoformat(),
            },
        }
        for m in rows
    ]
    return {"items": items, "next_offset": offset + limit if has_more else None}


async def search_chats(
    session: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    pattern = f"%{query}%"
    stmt = (
        select(Chat)
        .join(ChatMember, ChatMember.chat_id == Chat.id)
        .where(
            ChatMember.user_id == user_id,
            ChatMember.status == ChatMemberStatus.ACTIVE,
            Chat.deleted_at.is_(None),
            Chat.title.ilike(pattern),
        )
        .order_by(Chat.title)
        .limit(limit + 1)
        .offset(offset)
    )
    rows = (await session.scalars(stmt)).all()
    has_more = len(rows) > limit
    items = [
        {"type": "chat", "chat": {"id": str(c.id), "type": str(c.type), "title": c.title}}
        for c in rows[:limit]
    ]
    return {"items": items, "next_offset": offset + limit if has_more else None}


async def search_users(
    session: AsyncSession,
    query: str,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    pattern = f"%{query}%"
    stmt = (
        select(User)
        .where(User.is_deleted.is_(False))
        .where(or_(User.full_name.ilike(pattern), User.username.ilike(pattern)))
        .order_by(User.username)
        .limit(limit + 1)
        .offset(offset)
    )
    rows = (await session.scalars(stmt)).all()
    has_more = len(rows) > limit
    items = [
        {
            "type": "user",
            "user": {
                "id": str(u.id),
                "username": u.username,
                "full_name": u.full_name,
                "avatar_url": None,
                "title": u.title,
            },
        }
        for u in rows[:limit]
    ]
    return {"items": items, "next_offset": offset + limit if has_more else None}
