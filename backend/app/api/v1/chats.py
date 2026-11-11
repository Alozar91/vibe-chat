"""Чаты: REST-роуты (Docs/concept.md §12)."""

from datetime import UTC, datetime
from typing import Annotated

from app.api.deps import UserDep
from app.db.session import get_db
from app.models.chat import Chat
from app.schemas.chat import (
    ChatCreateIn,
    ChatDetailOut,
    ChatMemberOut,
    ChatOut,
    DirectCreatedOut,
    DirectCreateIn,
)
from app.services import chats as chat_service
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["chats"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.post("/chats", response_model=ChatOut, status_code=201)
async def create_group_chat(body: ChatCreateIn, me: UserDep, db: DbDep) -> ChatOut:
    chat = await chat_service.create_group(
        db, creator_id=me.id, title=body.title, member_ids=body.member_ids
    )
    return ChatOut.model_validate(chat)


@router.post("/chats/direct", response_model=DirectCreatedOut, status_code=201)
async def create_direct_chat(body: DirectCreateIn, me: UserDep, db: DbDep) -> DirectCreatedOut:
    chat, created = await chat_service.create_or_get_direct(
        db, me_id=me.id, other_id=body.user_id
    )
    return DirectCreatedOut(chat_id=chat.id, created=created)


@router.get("/chats", response_model=list[ChatOut])
async def list_chats(me: UserDep, db: DbDep) -> list[ChatOut]:
    chats = await chat_service.list_user_chats(db, me.id)
    return [ChatOut.model_validate(c) for c in chats]


@router.get("/chats/{chat_id}", response_model=ChatDetailOut)
async def get_chat(chat_id: str, me: UserDep, db: DbDep) -> ChatDetailOut:
    await chat_service.require_member(db, chat_id, me.id)
    chat = await db.get(Chat, chat_id)
    assert chat is not None
    members = await chat_service.list_chat_members(db, chat_id)
    base = ChatOut.model_validate(chat).model_dump()
    return ChatDetailOut(**base, members=[ChatMemberOut.model_validate(m) for m in members])


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
