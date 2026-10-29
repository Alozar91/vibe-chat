import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.valkey import publish_event
from app.db.session import session_factory
from app.models import OutboxEvent

logger = logging.getLogger("vibe.worker")


def ws_frame(event_type: str, chat_id: str | None, data: dict[str, Any]) -> dict[str, Any]:
    return {"type": event_type, "chat_id": chat_id, "data": data}


async def process_event(session: AsyncSession, event: OutboxEvent) -> None:
    payload = event.payload or {}
    if event.event_type == "message.created":
        await publish_event(
            ws_frame("message.new", str(event.chat_id), payload.get("message") or payload)
        )
        from worker.notify import notify_message_created

        await notify_message_created(session, event.chat_id, payload)
    elif event.event_type == "message.updated":
        await publish_event(ws_frame("message.updated", str(event.chat_id), payload))
    elif event.event_type == "message.deleted":
        await publish_event(ws_frame("message.deleted", str(event.chat_id), payload))
    elif event.event_type in ("chat.created", "chat.updated", "chat.deleted"):
        await publish_event(ws_frame(event.event_type, str(event.chat_id), payload))
    elif event.event_type in ("chat.member.joined", "chat.member.left"):
        await publish_event(ws_frame(event.event_type, str(event.chat_id), payload))
        user_id = payload.get("user_id")
        if user_id:
            await publish_event(
                {
                    "type": event.event_type,
                    "user_ids": [user_id],
                    "data": payload,
                }
            )
    elif event.event_type in ("bot.added_to_chat", "bot.removed_from_chat"):
        user_id = payload.get("user_id")
        await publish_event(ws_frame(event.event_type, str(event.chat_id), payload))
        if user_id:
            await publish_event(
                {
                    "type": event.event_type,
                    "user_ids": [user_id],
                    "data": payload,
                }
            )
    elif event.event_type == "chat.read":
        await publish_event(ws_frame("chat.read", str(event.chat_id), payload))
        user_id = payload.get("user_id")
        if user_id:
            unread = await _total_unread(session, user_id)
            await publish_event(
                {
                    "type": "notification.badge",
                    "user_ids": [user_id],
                    "data": {"unread_total": unread},
                }
            )
    elif event.event_type == "message.command":
        await publish_event(ws_frame("message.command", str(event.chat_id), payload))
    else:
        await publish_event(ws_frame(event.event_type, str(event.chat_id) if event.chat_id else None, payload))


async def _total_unread(session: AsyncSession, user_id: str) -> int:
    from sqlalchemy import BigInteger, cast, func

    from app.models import Chat, ChatMember, ChatMemberStatus

    total = (
        await session.scalar(
            select(
                cast(
                    func.coalesce(
                        func.sum(
                            func.greatest(Chat.last_message_seq - ChatMember.last_read_seq, 0)
                        ),
                        0,
                    ),
                    BigInteger,
                )
            )
            .select_from(ChatMember)
            .join(Chat, Chat.id == ChatMember.chat_id)
            .where(
                ChatMember.user_id == _uuid(user_id),
                ChatMember.status == ChatMemberStatus.ACTIVE,
                Chat.deleted_at.is_(None),
            )
        )
    )
    return int(total or 0)


def _uuid(value: str):
    import uuid as uuid_mod

    return uuid_mod.UUID(value)


async def run_consumer() -> None:
    logger.info("Outbox consumer запущен")
    while True:
        try:
            processed = await _process_batch()
            if not processed:
                import asyncio

                await asyncio.sleep(0.2)
        except Exception:
            logger.exception("Ошибка обработки outbox-пакета")
            import asyncio

            await asyncio.sleep(1.0)


async def _process_batch() -> int:
    async with session_factory() as session:
        rows = (
            (
                await session.scalars(
                    select(OutboxEvent)
                    .where(OutboxEvent.published_at.is_(None))
                    .order_by(OutboxEvent.seq)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        if not rows:
            return 0
        from app.core.timeutil import utcnow

        for event in rows:
            try:
                await process_event(session, event)
            except Exception:
                logger.exception("Не удалось обработать событие seq=%s", event.seq)
            event.published_at = utcnow()
        await session.commit()
        return len(rows)
