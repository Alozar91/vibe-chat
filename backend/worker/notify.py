import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.notifications_rules import should_push
from app.core.timeutil import utcnow
from app.core.valkey import get_valkey, publish_event
from app.models import Chat, ChatMember, ChatMemberStatus, Device, User

logger = logging.getLogger("vibe.notify")

BATCH = 500


async def notify_message_created(
    session: AsyncSession, chat_id: uuid.UUID | None, payload: dict[str, Any]
) -> None:
    if chat_id is None:
        return

    message = payload.get("message") or {}
    seq = message.get("seq")
    sender_id = message.get("sender_id")
    body = message.get("body") or ""
    mentions_all = bool(message.get("mentions_all"))
    mention_ids = {m.get("user_id") for m in (message.get("mentions") or []) if m.get("user_id")}
    if not seq or not sender_id:
        return

    valkey = get_valkey()
    chat = await session.get(Chat, chat_id)
    if chat is None:
        return
    sender_name_row = await session.get(User, uuid.UUID(str(sender_id)))
    sender_name = sender_name_row.full_name if sender_name_row else ""
    title = chat.title or (f"Личный чат: {sender_name}" if chat.type == "direct" else "Чат")

    offset = 0
    while True:
        rows = (
            await session.execute(
                select(ChatMember, User)
                .join(User, User.id == ChatMember.user_id)
                .where(ChatMember.chat_id == chat_id, ChatMember.status == ChatMemberStatus.ACTIVE)
                .order_by(ChatMember.user_id)
                .limit(BATCH)
                .offset(offset)
            )
        ).all()
        if not rows:
            break
        offset += BATCH
        targets: list[str] = []
        for member, user in rows:
            ns = user.notification_settings or {}
            decision = should_push(
                is_sender=str(user.id) == str(sender_id),
                mode=member.notifications,
                mentioned=str(user.id) in mention_ids,
                mentions_all=mentions_all,
                muted_until=member.muted_until,
                dnd_until=_parse_dt(ns.get("dnd_until")),
                online=False,
                now=utcnow(),
            )
            if not decision.push:
                continue
            if await valkey.exists(f"presence:{user.id}"):
                continue
            if chat.members_count > get_settings_safe().push_large_chat_threshold and not (
                str(user.id) in mention_ids or (mentions_all and member.role != "member")
            ):
                continue
            targets.append(str(user.id))
        if targets:
            await _push_to_users(session, valkey, targets, title, body, str(sender_id), sender_name)
        if len(rows) < BATCH:
            break

    for uid in list(mention_ids)[:50]:
        try:
            from worker.consumer import _total_unread

            unread = await _total_unread(session, uid)
        except Exception:
            continue
        await publish_event(
            {"type": "notification.badge", "user_ids": [uid], "data": {"unread_total": unread}}
        )


def get_settings_safe():
    from app.config import get_settings

    return get_settings()


def _parse_dt(value: Any):
    if not value:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def _push_to_users(
    session: AsyncSession,
    valkey,
    user_ids: list[str],
    title: str,
    body: str,
    sender_id: str,
    sender_name: str,
) -> None:
    from worker.senders import get_pusher

    settings = get_settings_safe()
    rows = (
        await session.scalars(select(Device).where(Device.user_id.in_([uuid.UUID(u) for u in user_ids])))
    ).all()
    pusher = get_pusher()
    text_body = body if settings.push_include_body else "Новое сообщение"
    for device in rows:
        try:
            await pusher.send(
                platform=device.platform,
                token=device.push_token,
                webpush_endpoint=device.webpush_endpoint,
                webpush_keys=device.webpush_keys,
                title=sender_name or title,
                body=text_body,
                sender_id=sender_id,
            )
        except Exception:
            logger.exception("Ошибка push для устройства %s", device.id)
