import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, ErrorCode, bad_request, forbidden, not_found
from app.core.outbox import add_event
from app.core.permissions import (
    can_add_members,
    can_create_invite,
    can_delete_chat,
    can_edit_chat,
    can_manage_bots_in_chat,
    can_remove_members,
)
from app.core.timeutil import utcnow
from app.models import (
    Chat,
    ChatInvite,
    ChatMember,
    ChatMemberRole,
    ChatMemberStatus,
    ChatType,
    DirectChat,
    User,
    UserKind,
    UserStatus,
)
from app.modules.users.service import serialize_user


async def get_chat_or_404(session: AsyncSession, chat_id: uuid.UUID) -> Chat:
    chat = await session.get(Chat, chat_id)
    if chat is None or chat.deleted_at is not None:
        raise not_found("Чат")
    return chat


async def get_membership(
    session: AsyncSession, chat_id: uuid.UUID, user_id: uuid.UUID
) -> ChatMember | None:
    return (
        await session.scalars(
            select(ChatMember).where(ChatMember.chat_id == chat_id, ChatMember.user_id == user_id)
        )
    ).one_or_none()


async def require_member(
    session: AsyncSession, chat_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[Chat, ChatMember]:
    chat = await get_chat_or_404(session, chat_id)
    member = await get_membership(session, chat_id, user_id)
    if member is None or member.status != ChatMemberStatus.ACTIVE:
        raise forbidden("Вы не участник чата", ErrorCode.CHAT_MEMBER_REQUIRED)
    return chat, member


def serialize_chat(
    chat: Chat, my_role: str, unread: int, muted_until: datetime | None = None
) -> dict[str, Any]:
    return {
        "id": str(chat.id),
        "type": str(chat.type),
        "title": chat.title,
        "description": chat.description,
        "avatar_url": chat.avatar_url,
        "created_by": str(chat.created_by) if chat.created_by else None,
        "members_count": chat.members_count,
        "last_message_seq": chat.last_message_seq,
        "last_message_at": chat.last_message_at.isoformat() if chat.last_message_at else None,
        "settings": chat.settings,
        "my_role": my_role,
        "unread": unread,
        "muted_until": muted_until.isoformat() if muted_until else None,
        "created_at": chat.created_at.isoformat(),
        "updated_at": chat.updated_at.isoformat(),
    }


def serialize_member(member: ChatMember, user: User) -> dict[str, Any]:
    return {
        "user": serialize_user(user),
        "role": str(member.role),
        "status": str(member.status),
        "last_read_seq": member.last_read_seq,
        "joined_at": member.joined_at.isoformat(),
    }


async def create_direct_chat(session: AsyncSession, me: uuid.UUID, other: uuid.UUID) -> Chat:
    if me == other:
        raise bad_request("Нельзя создать чат с самим собой")
    other_user = await session.get(User, other)
    if other_user is None or other_user.is_deleted or other_user.status != UserStatus.ACTIVE:
        raise not_found("Пользователь")
    pair = (
        await session.scalars(
            select(DirectChat).where(
                func.least(DirectChat.user_a, DirectChat.user_b) == min(me, other),
                func.greatest(DirectChat.user_a, DirectChat.user_b) == max(me, other),
            )
        )
    ).one_or_none()
    if pair is not None:
        chat = await get_chat_or_404(session, pair.chat_id)
        await session.execute(
            update(ChatMember)
            .where(
                ChatMember.chat_id == chat.id,
                ChatMember.user_id.in_([me, other]),
                ChatMember.status != ChatMemberStatus.ACTIVE,
            )
            .values(status=ChatMemberStatus.ACTIVE, joined_at=func.now(), left_at=None)
        )
        await session.commit()
        return chat
    a, b = sorted([me, other])
    chat = Chat(type=ChatType.DIRECT, created_by=me, members_count=2)
    session.add(chat)
    await session.flush()
    session.add(DirectChat(chat_id=chat.id, user_a=a, user_b=b))
    session.add_all(
        [
            ChatMember(chat_id=chat.id, user_id=me, role=ChatMemberRole.MEMBER),
            ChatMember(chat_id=chat.id, user_id=other, role=ChatMemberRole.MEMBER),
        ]
    )
    await add_event(
        session,
        aggregate_type="chat",
        aggregate_id=chat.id,
        event_type="chat.created",
        chat_id=chat.id,
        payload={"chat_type": "direct"},
    )
    await session.commit()
    return chat


async def create_group_chat(
    session: AsyncSession,
    me: uuid.UUID,
    title: str,
    description: str | None,
    member_ids: list[uuid.UUID],
    max_group_members: int,
) -> Chat:
    title = (title or "").strip()
    if not title or len(title) > 200:
        raise bad_request("title: 1..200 символов")
    unique_ids = {mid for mid in member_ids if mid != me}
    if len(unique_ids) + 1 > max_group_members:
        raise bad_request(f"Максимум участников группы: {max_group_members}")
    chat = Chat(
        type=ChatType.GROUP,
        title=title,
        description=description,
        created_by=me,
        settings={"who_can_add_members": "admins", "all_allowed": True},
        members_count=1,
    )
    session.add(chat)
    await session.flush()
    session.add(ChatMember(chat_id=chat.id, user_id=me, role=ChatMemberRole.OWNER))
    if unique_ids:
        rows = (await session.scalars(select(User).where(User.id.in_(unique_ids)))).all()
        found = {u.id for u in rows if not u.is_deleted and u.status == UserStatus.ACTIVE}
        for uid in found:
            session.add(
                ChatMember(chat_id=chat.id, user_id=uid, role=ChatMemberRole.MEMBER, invited_by=me)
            )
        chat.members_count = 1 + len(found)
    await add_event(
        session,
        aggregate_type="chat",
        aggregate_id=chat.id,
        event_type="chat.created",
        chat_id=chat.id,
        payload={"chat_type": "group", "title": title},
    )
    await session.commit()
    return chat


async def list_chats(
    session: AsyncSession, user_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int | None]:
    stmt = (
        select(Chat, ChatMember)
        .join(ChatMember, ChatMember.chat_id == Chat.id)
        .where(
            ChatMember.user_id == user_id,
            ChatMember.status == ChatMemberStatus.ACTIVE,
            Chat.deleted_at.is_(None),
        )
        .order_by(Chat.last_message_at.desc().nullslast(), Chat.created_at.desc())
        .limit(limit + 1)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    direct_ids = [chat.id for chat, _ in rows if chat.type == ChatType.DIRECT]
    counterparts: dict[uuid.UUID, User] = {}
    if direct_ids:
        dc_rows = (
            await session.execute(
                select(DirectChat, User)
                .join(User, User.id.in_([DirectChat.user_a, DirectChat.user_b]))
                .where(DirectChat.chat_id.in_(direct_ids), User.id != user_id)
            )
        ).all()
        for dc, user in dc_rows:
            counterparts[dc.chat_id] = user
    items = []
    for chat, member in rows:
        item = serialize_chat(
            chat, str(member.role), max(chat.last_message_seq - member.last_read_seq, 0), member.muted_until
        )
        counterpart = counterparts.get(chat.id)
        if counterpart is not None:
            item["counterpart"] = serialize_user(counterpart)
        items.append(item)
    return items, offset + limit if has_more else None


async def update_chat(
    session: AsyncSession, chat: Chat, member: ChatMember, payload: dict[str, Any]
) -> Chat:
    if not can_edit_chat(member.role):
        raise forbidden("Изменять настройки чата может владелец или админ")
    if "title" in payload:
        title = (payload.get("title") or "").strip()
        if not title or len(title) > 200:
            raise bad_request("title: 1..200 символов")
        chat.title = title
    if "description" in payload:
        description = (payload.get("description") or "").strip() or None
        if description and len(description) > 2000:
            raise bad_request("description: до 2000 символов")
        chat.description = description
    if "settings" in payload:
        settings = payload.get("settings") or {}
        if not isinstance(settings, dict):
            raise bad_request("settings: объект")
        who = settings.get("who_can_add_members")
        if who is not None and who not in ("admins", "all"):
            raise bad_request("who_can_add_members: admins|all")
        chat.settings = {**chat.settings, **settings}
    chat.updated_at = func.now()
    await add_event(
        session,
        aggregate_type="chat",
        aggregate_id=chat.id,
        event_type="chat.updated",
        chat_id=chat.id,
        payload={"chat_id": str(chat.id), "title": chat.title},
    )
    await session.commit()
    return chat


async def delete_chat(session: AsyncSession, chat: Chat, member: ChatMember) -> None:
    if not can_delete_chat(member.role):
        raise forbidden("Удалить чат может только владелец")
    if chat.type == ChatType.DIRECT:
        raise bad_request("Личный чат нельзя удалить")
    from app.core.timeutil import utcnow

    chat.deleted_at = utcnow()
    await add_event(
        session,
        aggregate_type="chat",
        aggregate_id=chat.id,
        event_type="chat.deleted",
        chat_id=chat.id,
        payload={"chat_id": str(chat.id)},
    )
    await session.commit()


async def add_members(
    session: AsyncSession,
    chat: Chat,
    actor: ChatMember,
    user_ids: list[uuid.UUID],
) -> dict[str, Any]:
    if not can_add_members(actor.role, chat.settings):
        raise forbidden("Добавлять участников может владелец/админ (или все, по настройке)")
    if not user_ids or len(user_ids) > 100:
        raise bad_request("user_ids: 1..100 элементов")
    if chat.type == ChatType.DIRECT:
        raise bad_request("В личный чат нельзя добавлять участников")
    users = {
        u.id: u
        for u in (
            await session.scalars(select(User).where(User.id.in_(set(user_ids))))
        ).all()
    }
    added: list[str] = []
    skipped: list[str] = []
    for uid in user_ids:
        user = users.get(uid)
        if user is None or user.is_deleted or user.status != UserStatus.ACTIVE:
            skipped.append(str(uid))
            continue
        if user.kind == UserKind.BOT and not can_manage_bots_in_chat(actor.role):
            raise forbidden("Добавлять ботов может владелец/админ чата")
        existing = await get_membership(session, chat.id, uid)
        if existing is not None and existing.status == ChatMemberStatus.ACTIVE:
            skipped.append(str(uid))
            continue
        if existing is not None and existing.status == ChatMemberStatus.BANNED:
            skipped.append(str(uid))
            continue
        if existing is not None:
            existing.status = ChatMemberStatus.ACTIVE
            existing.joined_at = func.now()
            existing.left_at = None
        else:
            session.add(
                ChatMember(chat_id=chat.id, user_id=uid, role=ChatMemberRole.MEMBER, invited_by=actor.user_id)
            )
        chat.members_count += 1
        added.append(str(uid))
        await add_system_message(session, chat, actor.user_id, f"{user.full_name} добавлен в чат")
        await add_event(
            session,
            aggregate_type="chat_member",
            aggregate_id=f"{chat.id}:{uid}",
            event_type="chat.member.joined" if user.kind != UserKind.BOT else "bot.added_to_chat",
            chat_id=chat.id,
            payload={
                "chat_id": str(chat.id),
                "user_id": str(uid),
                "actor_id": str(actor.user_id),
                "is_bot": user.kind == UserKind.BOT,
            },
        )
    await session.commit()
    return {"added": added, "skipped": skipped}


async def remove_member(
    session: AsyncSession, chat: Chat, actor: ChatMember, target_id: uuid.UUID
) -> None:
    if not can_remove_members(actor.role):
        raise forbidden("Удалять участников может владелец или админ")
    if chat.type == ChatType.DIRECT:
        raise bad_request("В личном чате нельзя удалять участников")
    target = await get_membership(session, chat.id, target_id)
    if target is None or target.status not in (ChatMemberStatus.ACTIVE, ChatMemberStatus.INVITED):
        raise not_found("Участник")
    if target.role == ChatMemberRole.OWNER:
        raise bad_request("Нельзя удалить владельца чата")
    target_user = await session.get(User, target_id)
    target.status = ChatMemberStatus.REMOVED
    target.left_at = func.now()
    chat.members_count = max(chat.members_count - 1, 0)
    if target_user is not None:
        await add_system_message(session, chat, actor.user_id, f"{target_user.full_name} удалён из чата")
    event = "bot.removed_from_chat" if (target_user and target_user.kind == UserKind.BOT) else "chat.member.left"
    await add_event(
        session,
        aggregate_type="chat_member",
        aggregate_id=f"{chat.id}:{target_id}",
        event_type=event,
        chat_id=chat.id,
        payload={"chat_id": str(chat.id), "user_id": str(target_id), "removed_by": str(actor.user_id)},
    )
    await session.commit()


async def leave_chat(session: AsyncSession, chat: Chat, member: ChatMember) -> None:
    if chat.type == ChatType.DIRECT:
        member.status = ChatMemberStatus.LEFT
        member.left_at = func.now()
        await session.commit()
        return
    if member.role == ChatMemberRole.OWNER:
        next_owner = (
            await session.scalars(
                select(ChatMember)
                .where(
                    ChatMember.chat_id == chat.id,
                    ChatMember.user_id != member.user_id,
                    ChatMember.status == ChatMemberStatus.ACTIVE,
                )
                .order_by(
                    case((ChatMember.role == ChatMemberRole.ADMIN, 0), else_=1),
                    ChatMember.joined_at,
                )
                .limit(1)
            )
        ).one_or_none()
        if next_owner is None:
            raise bad_request("Вы последний участник: удалите чат вместо выхода")
        member.role = ChatMemberRole.MEMBER
        next_owner.role = ChatMemberRole.OWNER
        chat.created_by = next_owner.user_id
        await add_system_message(session, chat, member.user_id, "Владелец вышел; новый владелец назначен")
    member.status = ChatMemberStatus.LEFT
    member.left_at = func.now()
    chat.members_count = max(chat.members_count - 1, 0)
    await add_event(
        session,
        aggregate_type="chat_member",
        aggregate_id=f"{chat.id}:{member.user_id}",
        event_type="chat.member.left",
        chat_id=chat.id,
        payload={"chat_id": str(chat.id), "user_id": str(member.user_id), "left": True},
    )
    await session.commit()


async def mark_read(
    session: AsyncSession, chat: Chat, member: ChatMember, last_read_seq: int
) -> int:
    if last_read_seq < 0 or last_read_seq > chat.last_message_seq:
        raise bad_request("last_read_seq вне диапазона")
    member.last_read_seq = max(member.last_read_seq, last_read_seq)
    member.last_read_at = func.now()
    await add_event(
        session,
        aggregate_type="chat_member",
        aggregate_id=f"{chat.id}:{member.user_id}",
        event_type="chat.read",
        chat_id=chat.id,
        payload={"chat_id": str(chat.id), "user_id": str(member.user_id), "last_read_seq": member.last_read_seq},
    )
    await session.commit()
    return max(chat.last_message_seq - member.last_read_seq, 0)


async def update_my_membership(
    session: AsyncSession, member: ChatMember, payload: dict[str, Any]
) -> ChatMember:
    if payload.get("notifications") is not None:
        mode = payload.get("notifications")
        if mode not in ("all", "mentions", "none"):
            raise bad_request("notifications: all|mentions|none")
        member.notifications = mode
    if "muted_until" in payload:
        muted = payload.get("muted_until")
        if muted is not None:
            from datetime import datetime

            try:
                muted = datetime.fromisoformat(str(muted).replace("Z", "+00:00"))
            except ValueError as exc:
                raise bad_request("muted_until: ISO 8601") from exc
        member.muted_until = muted
    await session.commit()
    return member


async def add_system_message(session: AsyncSession, chat: Chat, actor_id: uuid.UUID, text: str) -> None:
    from app.core.timeutil import utcnow
    from app.models import Message, MessageType

    seq = (
        await session.execute(
            update(Chat)
            .where(Chat.id == chat.id)
            .values(last_message_seq=Chat.last_message_seq + 1, last_message_at=utcnow())
            .returning(Chat.last_message_seq)
        )
    ).scalar_one()
    message = Message(chat_id=chat.id, seq=seq, sender_id=actor_id, type=MessageType.SYSTEM, body=text)
    session.add(message)
    await add_event(
        session,
        aggregate_type="message",
        aggregate_id=f"{chat.id}:{seq}",
        event_type="message.created",
        chat_id=chat.id,
        payload={
            "chat_id": str(chat.id),
            "seq": seq,
            "message_type": "system",
            "body": text,
            "sender_id": str(actor_id),
        },
    )


async def create_invite(
    session: AsyncSession,
    chat: Chat,
    actor: ChatMember,
    expires_at: datetime | None,
    max_uses: int | None,
    domain_limit: str | None,
) -> ChatInvite:
    if chat.type != ChatType.GROUP:
        raise bad_request("Приглашения доступны только для групп")
    if not can_create_invite(actor.role):
        raise forbidden("Создавать приглашения может владелец или админ")
    if max_uses is not None and max_uses < 1:
        raise bad_request("max_uses: >= 1")
    from app.core.security import generate_invite_code

    invite = ChatInvite(
        chat_id=chat.id,
        code=generate_invite_code(),
        created_by=actor.user_id,
        domain_limit=domain_limit,
        expires_at=expires_at,
        max_uses=max_uses,
        uses=0,
    )
    session.add(invite)
    await session.commit()
    return invite


def serialize_invite(invite: ChatInvite, base_url: str) -> dict[str, Any]:
    return {
        "id": str(invite.id),
        "chat_id": str(invite.chat_id),
        "code": invite.code,
        "url": f"{base_url.rstrip('/')}/join/{invite.code}",
        "uses": invite.uses,
        "max_uses": invite.max_uses,
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        "revoked_at": invite.revoked_at.isoformat() if invite.revoked_at else None,
        "created_at": invite.created_at.isoformat(),
    }


async def list_invites(
    session: AsyncSession, chat: Chat, actor: ChatMember
) -> list[dict[str, Any]]:
    if not can_create_invite(actor.role):
        raise forbidden("Просматривать приглашения может владелец или админ")
    from app.config import get_settings

    rows = (
        await session.scalars(
            select(ChatInvite)
            .where(ChatInvite.chat_id == chat.id, ChatInvite.revoked_at.is_(None))
            .order_by(ChatInvite.created_at.desc())
        )
    ).all()
    base = get_settings().public_base_url
    return [serialize_invite(invite, base) for invite in rows]


async def revoke_invite(
    session: AsyncSession, chat: Chat, actor: ChatMember, invite_id: uuid.UUID
) -> None:
    if not can_create_invite(actor.role):
        raise forbidden("Отзывать приглашения может владелец или админ")
    invite = await session.get(ChatInvite, invite_id)
    if invite is None or invite.chat_id != chat.id or invite.revoked_at is not None:
        raise not_found("Приглашение")
    from app.core.timeutil import utcnow

    invite.revoked_at = utcnow()
    await session.commit()


async def join_by_code(
    session: AsyncSession, user_id: uuid.UUID, code: str
) -> Chat:
    invite = (
        await session.scalars(select(ChatInvite).where(ChatInvite.code == code))
    ).one_or_none()
    now = utcnow()
    if invite is None or invite.revoked_at is not None:
        raise not_found("Приглашение")
    if invite.expires_at is not None and invite.expires_at < now:
        raise ApiError(410, ErrorCode.CONFLICT, "Приглашение истекло")
    if invite.max_uses is not None and invite.uses >= invite.max_uses:
        raise ApiError(429, ErrorCode.RATE_LIMITED, "Лимит использований исчерпан")
    chat = await get_chat_or_404(session, invite.chat_id)
    if chat.members_count >= 100000:
        raise bad_request("Чат переполнен")
    existing = await get_membership(session, chat.id, user_id)
    if existing is not None and existing.status == ChatMemberStatus.ACTIVE:
        return chat
    if existing is not None and existing.status == ChatMemberStatus.BANNED:
        raise forbidden("Вы не можете вступить в этот чат")
    if existing is not None:
        existing.status = ChatMemberStatus.ACTIVE
        existing.joined_at = func.now()
        existing.left_at = None
    else:
        session.add(
            ChatMember(chat_id=chat.id, user_id=user_id, role=ChatMemberRole.MEMBER, invited_by=invite.created_by)
        )
        chat.members_count += 1
    invite.uses += 1
    joiner = await session.get(User, user_id)
    joiner_name = joiner.full_name if joiner else "Участник"
    await add_system_message(session, chat, invite.created_by, f"{joiner_name} присоединился по ссылке")
    await add_event(
        session,
        aggregate_type="chat_member",
        aggregate_id=f"{chat.id}:{user_id}",
        event_type="chat.member.joined",
        chat_id=chat.id,
        payload={"chat_id": str(chat.id), "user_id": str(user_id), "actor_id": str(user_id)},
    )
    await session.commit()
    return chat


async def change_member_role(
    session: AsyncSession, chat: Chat, actor: ChatMember, target_id: uuid.UUID, new_role: ChatMemberRole
) -> None:
    if actor.role != ChatMemberRole.OWNER:
        raise forbidden("Назначать роли может только владелец")
    if new_role == ChatMemberRole.OWNER:
        raise bad_request("Передача владения через смену роли недоступна")
    target = await get_membership(session, chat.id, target_id)
    if target is None or target.status != ChatMemberStatus.ACTIVE:
        raise not_found("Участник")
    target.role = new_role
    await session.commit()
