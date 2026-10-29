import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import bad_request
from app.core.security import AuthContext
from app.db.session import get_session
from app.models import ChatMember, ChatMemberStatus, User
from app.modules.auth.dependencies import get_auth_context, require_csrf
from app.modules.chats import service as chats_service

router = APIRouter(prefix="/v1/chats", tags=["chats"], dependencies=[Depends(require_csrf)])
invites_router = APIRouter(prefix="/v1/invites", tags=["invites"], dependencies=[Depends(require_csrf)])


class ChatCreate(BaseModel):
    model_config = {"extra": "forbid"}

    type: str
    title: str | None = None
    description: str | None = None
    user_id: str | None = None
    member_ids: list[str] = Field(default_factory=list)


class ChatUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = None
    description: str | None = None
    settings: dict | None = None


class MembersAdd(BaseModel):
    model_config = {"extra": "forbid"}

    user_ids: list[str]
    role: str = "member"


class ReadPayload(BaseModel):
    model_config = {"extra": "forbid"}

    last_read_seq: int


class MemberSelfUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    notifications: str | None = None
    muted_until: str | None = None


class InviteCreate(BaseModel):
    model_config = {"extra": "forbid"}

    expires_at: str | None = None
    max_uses: int | None = None
    domain_limit: str | None = None


def _uuid_list(values: list[str], field: str) -> list[uuid.UUID]:
    try:
        return [uuid.UUID(v) for v in values]
    except ValueError as exc:
        raise bad_request(f"{field}: некорректный UUID") from exc


def _dt(value: str | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise bad_request(f"{field_name}: ISO 8601") from exc


@router.get("")
async def list_chats(
    limit: int | None = Query(default=None, ge=1, le=100),
    offset: int | None = Query(default=None, ge=0),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    items, next_offset = await chats_service.list_chats(db, ctx.user_id, limit or 50, offset or 0)
    return {"items": items, "next_offset": next_offset}


@router.post("")
async def create_chat(
    payload: ChatCreate,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    settings = get_settings()
    if payload.type == "direct":
        if not payload.user_id:
            raise bad_request("user_id обязателен для direct")
        chat = await chats_service.create_direct_chat(db, ctx.user_id, uuid.UUID(payload.user_id))
    elif payload.type == "group":
        chat = await chats_service.create_group_chat(
            db,
            ctx.user_id,
            payload.title or "",
            payload.description,
            _uuid_list(payload.member_ids, "member_ids"),
            settings.max_group_members,
        )
    else:
        raise bad_request("type: direct|group")
    member = await chats_service.get_membership(db, chat.id, ctx.user_id)
    role = str(member.role) if member else "member"
    unread = max(chat.last_message_seq - (member.last_read_seq if member else 0), 0)
    return chats_service.serialize_chat(chat, role, unread, member.muted_until if member else None)


@router.get("/{chat_id}")
async def get_chat(
    chat_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    chat, member = await chats_service.require_member(db, uuid.UUID(chat_id), ctx.user_id)
    unread = max(chat.last_message_seq - member.last_read_seq, 0)
    return chats_service.serialize_chat(chat, str(member.role), unread, member.muted_until)


@router.patch("/{chat_id}")
async def update_chat(
    chat_id: str,
    payload: ChatUpdate,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    chat, member = await chats_service.require_member(db, uuid.UUID(chat_id), ctx.user_id)
    updated = await chats_service.update_chat(db, chat, member, payload.model_dump(exclude_none=True))
    return chats_service.serialize_chat(updated, str(member.role), 0)


@router.delete("/{chat_id}")
async def delete_chat(
    chat_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> Response:
    chat, member = await chats_service.require_member(db, uuid.UUID(chat_id), ctx.user_id)
    await chats_service.delete_chat(db, chat, member)
    return Response(status_code=204)


@router.get("/{chat_id}/members")
async def list_members(
    chat_id: str,
    limit: int | None = Query(default=None, ge=1, le=100),
    offset: int | None = Query(default=None, ge=0),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    chat, _ = await chats_service.require_member(db, uuid.UUID(chat_id), ctx.user_id)
    limit_value, offset_value = (limit or 50, offset or 0)
    rows = (
        await db.execute(
            select(ChatMember, User)
            .join(User, User.id == ChatMember.user_id)
            .where(ChatMember.chat_id == chat.id, ChatMember.status == ChatMemberStatus.ACTIVE)
            .order_by(ChatMember.joined_at)
            .limit(limit_value + 1)
            .offset(offset_value)
        )
    ).all()
    has_more = len(rows) > limit_value
    rows = rows[:limit_value]
    items = [chats_service.serialize_member(member, user) for member, user in rows]
    return {"items": items, "next_offset": offset_value + limit_value if has_more else None}


@router.post("/{chat_id}/members")
async def add_members(
    chat_id: str,
    payload: MembersAdd,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    chat, member = await chats_service.require_member(db, uuid.UUID(chat_id), ctx.user_id)
    return await chats_service.add_members(db, chat, member, _uuid_list(payload.user_ids, "user_ids"))


@router.delete("/{chat_id}/members/{user_id}")
async def remove_member(
    chat_id: str,
    user_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> Response:
    chat, member = await chats_service.require_member(db, uuid.UUID(chat_id), ctx.user_id)
    await chats_service.remove_member(db, chat, member, uuid.UUID(user_id))
    return Response(status_code=204)


@router.post("/{chat_id}/leave")
async def leave_chat(
    chat_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> Response:
    chat, member = await chats_service.require_member(db, uuid.UUID(chat_id), ctx.user_id)
    await chats_service.leave_chat(db, chat, member)
    return Response(status_code=204)


@router.post("/{chat_id}/read")
async def mark_read(
    chat_id: str,
    payload: ReadPayload,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    chat, member = await chats_service.require_member(db, uuid.UUID(chat_id), ctx.user_id)
    unread = await chats_service.mark_read(db, chat, member, payload.last_read_seq)
    return {"unread": unread}


@router.patch("/{chat_id}/members/me")
async def update_my_membership(
    chat_id: str,
    payload: MemberSelfUpdate,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    chat, member = await chats_service.require_member(db, uuid.UUID(chat_id), ctx.user_id)
    updated = await chats_service.update_my_membership(db, member, payload.model_dump())
    return {
        "chat_id": str(chat.id),
        "notifications": updated.notifications,
        "muted_until": updated.muted_until.isoformat() if updated.muted_until else None,
    }


@router.post("/{chat_id}/invites")
async def create_invite(
    chat_id: str,
    payload: InviteCreate,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    chat, member = await chats_service.require_member(db, uuid.UUID(chat_id), ctx.user_id)
    invite = await chats_service.create_invite(
        db, chat, member, _dt(payload.expires_at, "expires_at"), payload.max_uses, payload.domain_limit
    )
    return chats_service.serialize_invite(invite, get_settings().public_base_url)


@router.get("/{chat_id}/invites")
async def list_invites(
    chat_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    chat, member = await chats_service.require_member(db, uuid.UUID(chat_id), ctx.user_id)
    return {"items": await chats_service.list_invites(db, chat, member)}


@router.delete("/{chat_id}/invites/{invite_id}")
async def revoke_invite(
    chat_id: str,
    invite_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> Response:
    chat, member = await chats_service.require_member(db, uuid.UUID(chat_id), ctx.user_id)
    await chats_service.revoke_invite(db, chat, member, uuid.UUID(invite_id))
    return Response(status_code=204)


@invites_router.post("/join/{code}")
async def join_by_code(
    code: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    chat = await chats_service.join_by_code(db, ctx.user_id, code)
    member = await chats_service.get_membership(db, chat.id, ctx.user_id)
    role = str(member.role) if member else "member"
    unread = max(chat.last_message_seq - (member.last_read_seq if member else 0), 0)
    return chats_service.serialize_chat(chat, role, unread)
