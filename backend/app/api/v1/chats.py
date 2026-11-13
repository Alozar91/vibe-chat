"""Чаты: REST-роуты (Docs/concept.md §12)."""

from datetime import UTC, datetime
from typing import Annotated

from app.api.deps import UserDep
from app.db.session import get_db
from app.models.chat import Chat, ChatMember
from app.models.message import Message
from app.models.user import User
from app.schemas.chat import (
    ChatCreateIn,
    ChatDetailOut,
    ChatMemberOut,
    ChatOut,
    ChatRenameIn,
    DirectCreatedOut,
    DirectCreateIn,
    MemberRoleIn,
)
from app.schemas.user import UserOut
from app.services import chats as chat_service
from app.services import realtime as rt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["chats"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
ChatId = str  # тайп-алиас для читаемости аннотаций роутов


async def _chat_outs(db: AsyncSession, chats: list[Chat], me_id: str) -> list[ChatOut]:
    """ChatOut с last_message_at (created_at последнего сообщения, §12) и unread_count.

    unread_count — сообщения чата с id > last_read_message_id получателя,
    не его собственные и не system. Курсоры — одним запросом; счётчики —
    по запросу на чат (десятки чатов на пользователя — дёшево, §9).
    """
    if not chats:
        return []
    chat_ids = [c.id for c in chats]

    last_rows = (
        await db.execute(
            select(Message.chat_id, func.max(Message.id))
            .where(Message.chat_id.in_(chat_ids))
            .group_by(Message.chat_id)
        )
    ).all()
    last_map = {cid: mid for cid, mid in last_rows}

    cursors = (
        await db.execute(
            select(ChatMember.chat_id, ChatMember.last_read_message_id).where(
                ChatMember.chat_id.in_(chat_ids), ChatMember.user_id == me_id
            )
        )
    ).all()
    cursor_map = {cid: cur for cid, cur in cursors}

    last_msgs: dict[str, datetime | None] = {}
    if last_map:
        rows = (
            await db.execute(
                select(Message.id, Message.created_at).where(Message.id.in_(list(last_map.values())))
            )
        ).all()
        last_msgs = {mid: ts for mid, ts in rows}

    unread_map: dict[str, int] = {}
    for cid in chat_ids:
        stmt = (
            select(func.count())
            .select_from(Message)
            .where(Message.chat_id == cid, Message.sender_id != me_id, Message.type != "system")
        )
        cur = cursor_map.get(cid)
        if cur is not None:
            stmt = stmt.where(Message.id > cur)
        unread_map[cid] = int(await db.scalar(stmt) or 0)

    outs: list[ChatOut] = []
    for c in chats:
        out = ChatOut.model_validate(c)
        mid = last_map.get(c.id)
        ts = last_msgs.get(mid) if mid else None
        out.last_message_at = ts  # сериализацию делает FastAPI (ISO 8601 UTC)
        out.unread_count = unread_map.get(c.id, 0)
        outs.append(out)
    return outs


@router.post("/chats", response_model=ChatOut, status_code=201)
async def create_group_chat(body: ChatCreateIn, me: UserDep, db: DbDep) -> ChatOut:
    chat = await chat_service.create_group(
        db, creator_id=me.id, title=body.title, member_ids=body.member_ids
    )
    # участникам — о новом чате (§9): во фронтовых вкладках список обновится сам
    await rt.publish_chat_created(db, chat.id)
    return (await _chat_outs(db, [chat], me.id))[0]


@router.post("/chats/direct", response_model=DirectCreatedOut, status_code=201)
async def create_direct_chat(body: DirectCreateIn, me: UserDep, db: DbDep) -> DirectCreatedOut:
    chat, created = await chat_service.create_or_get_direct(
        db, me_id=me.id, other_id=body.user_id
    )
    if created:
        # участникам (включая создателя в других вкладках) — о новом чате (§9)
        await rt.publish_chat_created(db, chat.id)
    return DirectCreatedOut(chat_id=chat.id, created=created)


@router.get("/chats", response_model=list[ChatOut])
async def list_chats(me: UserDep, db: DbDep) -> list[ChatOut]:
    chats = await chat_service.list_user_chats(db, me.id)
    return await _chat_outs(db, chats, me.id)


@router.get("/chats/{chat_id}", response_model=ChatDetailOut)
async def get_chat(chat_id: ChatId, me: UserDep, db: DbDep) -> ChatDetailOut:
    await chat_service.require_member(db, chat_id, me.id)
    chat = await db.get(Chat, chat_id)
    assert chat is not None
    # user в ответе обязателен (§12): фронт строит имена direct-чатов из members[].user
    rows = await db.execute(
        select(ChatMember, User)
        .join(User, User.id == ChatMember.user_id)
        .where(ChatMember.chat_id == chat_id)
        .order_by(ChatMember.joined_at)
    )
    members = [
        ChatMemberOut(
            user_id=m.user_id,
            role=m.role,
            last_read_message_id=m.last_read_message_id,
            user=UserOut.model_validate(u),
        )
        for m, u in rows.all()
    ]
    base = ChatOut.model_validate(chat).model_dump()
    return ChatDetailOut(**base, members=members)


@router.post("/chats/{chat_id}/members", status_code=204)
async def add_members(chat_id: str, body: ChatCreateIn, me: UserDep, db: DbDep) -> None:
    # тело переиспользуем: member_ids[]; title игнорируется
    await chat_service.add_members(
        db, chat_id=chat_id, actor_id=me.id, member_ids=body.member_ids
    )


@router.delete("/chats/{chat_id}/members/{user_id}", status_code=204)
async def remove_member(chat_id: str, user_id: str, me: UserDep, db: DbDep) -> None:
    await chat_service.remove_member(
        db, chat_id=chat_id, actor_id=me.id, target_id=user_id
    )


@router.patch("/chats/{chat_id}", response_model=ChatOut)
async def rename_chat(chat_id: str, body: ChatRenameIn, me: UserDep, db: DbDep) -> ChatOut:
    """Переименование группы (admin/owner, §12): system-сообщение + chat.updated (§9)."""
    chat = await chat_service.rename_group(db, chat_id=chat_id, actor_id=me.id, title=body.title)
    await rt.publish_chat_event(db, chat_id, "chat.updated", {})
    return (await _chat_outs(db, [chat], me.id))[0]


@router.patch("/chats/{chat_id}/members/{user_id}", response_model=ChatMemberOut)
async def set_member_role(chat_id: str, user_id: str, body: MemberRoleIn, me: UserDep, db: DbDep) -> ChatMemberOut:
    """Смена роли участника (owner, этап 12): member↔admin."""
    member = await chat_service.set_member_role(
        db, chat_id=chat_id, actor_id=me.id, target_id=user_id, role=body.role
    )
    user = await db.get(User, user_id)
    assert user is not None
    return ChatMemberOut(
        user_id=member.user_id,
        role=member.role,
        last_read_message_id=member.last_read_message_id,
        user=UserOut.model_validate(user),
    )


@router.post("/chats/{chat_id}/owner", status_code=204)
async def transfer_ownership(chat_id: str, body: DirectCreateIn, me: UserDep, db: DbDep) -> None:
    # {user_id} — новый owner
    await chat_service.transfer_ownership(
        db, chat_id=chat_id, actor_id=me.id, new_owner_id=body.user_id
    )


@router.delete("/chats/{chat_id}", status_code=204)
async def delete_chat(chat_id: str, me: UserDep, db: DbDep) -> None:
    member = await chat_service.require_member(db, chat_id, me.id)
    if member.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner role required")
    chat = await db.get(Chat, chat_id)
    assert chat is not None
    chat.deleted_at = datetime.now(UTC)
    await db.commit()
    # всем участникам — chat.updated {deleted: true} (§9): чат исчезнет из списков
    await rt.publish_chat_deleted(db, chat_id)
