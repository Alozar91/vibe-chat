"""Чаты: создание direct/group, участники, права (Docs/concept.md §6, §12)."""

import uuid

from app.models.chat import Chat, ChatMember, DirectChatKey
from app.models.user import User
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _uuid() -> str:
    return str(uuid.uuid4())


def _sorted_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


async def _get_active_user(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return user


async def get_member(db: AsyncSession, chat_id: str, user_id: str) -> ChatMember | None:
    return await db.get(ChatMember, (chat_id, user_id))


async def require_member(db: AsyncSession, chat_id: str, user_id: str) -> ChatMember:
    """Membership-проверка (§5): не участник — 403; чат не существует — 404."""
    chat = await db.get(Chat, chat_id)
    if chat is None or chat.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "chat not found")
    member = await get_member(db, chat_id, user_id)
    if member is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not a member")
    return member


async def require_chat_admin(db: AsyncSession, chat_id: str, user_id: str) -> ChatMember:
    member = await require_member(db, chat_id, user_id)
    if member.role not in ("owner", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
    return member


async def create_group(
    db: AsyncSession, *, creator_id: str, title: str, member_ids: list[str]
) -> Chat:
    """Групповой чат: creator = owner; member_ids >= 1; creator в списке игнорируется; боты допустимы (§12)."""
    others = [uid for uid in dict.fromkeys(member_ids) if uid != creator_id]
    for uid in others:
        await _get_active_user(db, uid)

    chat = Chat(id=_uuid(), type="group", title=title, created_by=creator_id)
    db.add(chat)
    db.add(ChatMember(chat_id=chat.id, user_id=creator_id, role="owner"))
    for uid in others:
        db.add(ChatMember(chat_id=chat.id, user_id=uid, role="member"))
    await db.commit()
    await db.refresh(chat)
    return chat


async def create_or_get_direct(db: AsyncSession, *, me_id: str, other_id: str) -> tuple[Chat, bool]:
    """Direct: пара не может породить два чата (direct_chat_keys, §6). Self-chat — 422 (§6)."""
    if me_id == other_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "self-chat not supported in MVP")
    await _get_active_user(db, other_id)

    user_a, user_b = _sorted_pair(me_id, other_id)
    existing_key = (
        await db.scalars(
            select(DirectChatKey).where(
                DirectChatKey.user_a == user_a, DirectChatKey.user_b == user_b
            )
        )
    ).first()
    if existing_key is not None:
        chat = await db.get(Chat, existing_key.chat_id)
        assert chat is not None
        return chat, False

    chat = Chat(id=_uuid(), type="direct", title=None, created_by=me_id)
    db.add(chat)
    db.add(ChatMember(chat_id=chat.id, user_id=me_id, role="member"))
    db.add(ChatMember(chat_id=chat.id, user_id=other_id, role="member"))
    db.add(DirectChatKey(chat_id=chat.id, user_a=user_a, user_b=user_b))
    await db.commit()
    await db.refresh(chat)
    return chat, True


async def add_members(db: AsyncSession, *, chat_id: str, actor_id: str, member_ids: list[str]) -> list[str]:
    """Добавление участников (admin/owner). Уже состоящие пропускаются — идемпотентно (§12)."""
    await require_chat_admin(db, chat_id, actor_id)
    added: list[str] = []
    for uid in dict.fromkeys(member_ids):
        if await get_member(db, chat_id, uid) is not None:
            continue
        await _get_active_user(db, uid)
        db.add(ChatMember(chat_id=chat_id, user_id=uid, role="member"))
        added.append(uid)
    await db.commit()
    return added


async def remove_member(db: AsyncSession, *, chat_id: str, actor_id: str, target_id: str) -> None:
    """Исключение участника: чат-админ исключает; owner'а исключить нельзя (§6)."""
    actor = await require_member(db, chat_id, actor_id)
    target = await require_member(db, chat_id, target_id)
    if target.role == "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot remove chat owner")
    if actor.role not in ("owner", "admin") and actor_id != target_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
    if actor.role == "admin" and target.role == "admin" and actor_id != target_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin cannot remove admin")
    await db.delete(target)
    await db.commit()


async def transfer_ownership(db: AsyncSession, *, chat_id: str, actor_id: str, new_owner_id: str) -> None:
    """Передача владения: бывший owner -> admin, новый -> owner (§6)."""
    actor = await require_member(db, chat_id, actor_id)
    if actor.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner role required")
    new_owner = await require_member(db, chat_id, new_owner_id)
    if new_owner.user_id == actor_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "already owner")
    actor.role = "admin"
    new_owner.role = "owner"
    await db.commit()


async def list_user_chats(db: AsyncSession, user_id: str) -> list[Chat]:
    stmt = (
        select(Chat)
        .join(ChatMember, ChatMember.chat_id == Chat.id)
        .where(ChatMember.user_id == user_id, Chat.deleted_at.is_(None))
        .order_by(Chat.created_at.desc())
    )
    return list((await db.scalars(stmt)).all())


async def list_chat_members(db: AsyncSession, chat_id: str) -> list[ChatMember]:
    stmt = select(ChatMember).where(ChatMember.chat_id == chat_id).order_by(ChatMember.joined_at)
    return list((await db.scalars(stmt)).all())
