"""Звонки: lifecycle (ringing → active → ended), участники, system-сообщения (§17).

Direct — ringing-модель (accept/reject/cancel); group — join-модель (join/leave).
Сигналинг звонка — WS-события call.* поверх существующего fanout (§9);
медиа-сигналинг идёт мимо бэкенда — в LiveKit по room-токену (§17).
"""

from datetime import UTC, datetime
from typing import Any

from app.models.call import Call, CallParticipant
from app.models.chat import Chat
from app.models.user import User
from app.services import realtime as rt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

CALL_TIMEOUT_SECONDS = 45  # ringing дольше — ended (+ call_missed), §17


def _new_call_id() -> str:
    """UUIDv7 — room name LiveKit и PK одновременно (§17)."""
    import uuid6

    return str(uuid6.uuid7())


def _now() -> datetime:
    return datetime.now(UTC)


def serialize_call(call: Call, participants: list[CallParticipant]) -> dict[str, Any]:
    """CallOut: текущий состав (left_at IS NULL) для UI звонка (§17)."""
    return {
        "id": call.id,
        "chat_id": call.chat_id,
        "initiator_id": call.initiator_id,
        "kind": call.kind,
        "status": call.status,
        "created_at": call.created_at.isoformat(),
        "started_at": call.started_at.isoformat() if call.started_at else None,
        "ended_at": call.ended_at.isoformat() if call.ended_at else None,
        "participant_ids": [p.user_id for p in participants if p.left_at is None],
    }


async def get_call_checked(db: AsyncSession, call_id: str) -> Call:
    call = await db.get(Call, call_id)
    if call is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "call not found")
    return call


async def _participants(db: AsyncSession, call_id: str) -> list[CallParticipant]:
    stmt = select(CallParticipant).where(CallParticipant.call_id == call_id)
    return list((await db.scalars(stmt)).all())


async def _active_participants(db: AsyncSession, call_id: str) -> list[CallParticipant]:
    return [p for p in await _participants(db, call_id) if p.left_at is None]


async def get_call_out(db: AsyncSession, call: Call) -> dict[str, Any]:
    return serialize_call(call, await _participants(db, call.id))


async def _publish_call(
    db: AsyncSession, call: Call, event_type: str, extra: dict[str, Any] | None = None
) -> None:
    """call.* участникам чата: {call: <CallOut>} (+ extra) — в user:{id} каждого (§9)."""
    data = {"call": await get_call_out(db, call), **(extra or {})}
    for user_id in await rt.chat_member_ids(db, call.chat_id):
        await rt.publish_to_user(user_id, event_type, data)


def _ensure_active_user(user: User) -> None:
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account deactivated")


async def start_call(
    db: AsyncSession, *, actor: User, chat_id: str, kind: str
) -> tuple[Call, bool]:
    """Создание звонка; повторный ringing того же инициатора — возвращается существующий (§17)."""
    from app.services import chats as chat_service

    if kind not in ("audio", "video"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "kind must be audio|video")
    if actor.is_bot:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bots do not make calls")
    await chat_service.require_member(db, chat_id, actor.id)
    _ensure_active_user(actor)

    # активный/ringing звонок в чате? — возвращаем его (без нового ринга)
    stmt = select(Call).where(Call.chat_id == chat_id, Call.status != "ended").order_by(Call.id.desc())
    existing = (await db.scalars(stmt)).first()
    if existing is not None:
        if existing.status == "active" or existing.initiator_id == actor.id:
            return existing, False
        # чужой незавершённый ринг — занято: 409
        raise HTTPException(status.HTTP_409_CONFLICT, "another call is in progress")

    chat = await db.get(Chat, chat_id)
    # §17, этап B: group — join-модель, комната открывается сразу active
    # (без ринга каждому; остальные узнают по call.joined). direct — ringing.
    initial_status = "active" if chat is not None and chat.type == "group" else "ringing"
    call = Call(
        id=_new_call_id(),
        chat_id=chat_id,
        initiator_id=actor.id,
        kind=kind,
        status=initial_status,
    )
    db.add(call)
    await db.flush()
    db.add(CallParticipant(call_id=call.id, user_id=actor.id))
    if initial_status == "active":
        call.started_at = _now()
    await db.commit()
    await _publish_call(db, call, "call.joined" if initial_status == "active" else "call.ring")
    return call, True


async def accept_call(db: AsyncSession, *, actor: User, call_id: str) -> Call:
    """Direct: ответил — ringing → active; call.accepted (§17)."""
    call = await get_call_checked(db, call_id)
    if call.chat_id:
        from app.services import chats as chat_service

        await chat_service.require_member(db, call.chat_id, actor.id)
    if call.status != "ringing":
        raise HTTPException(status.HTTP_409_CONFLICT, f"call is {call.status}, not ringing")
    if actor.is_bot:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bots do not make calls")
    call.status = "active"
    call.started_at = _now()
    part = await db.get(CallParticipant, (call.id, actor.id))
    if part is None:
        db.add(CallParticipant(call_id=call.id, user_id=actor.id))
    elif part.left_at is not None:
        part.left_at = None
    await db.commit()
    await _publish_call(db, call, "call.accepted")
    return call


async def reject_call(db: AsyncSession, *, actor: User, call_id: str) -> Call:
    """Direct: отказ — звонок завершается; call.rejected (§17)."""
    call = await get_call_checked(db, call_id)
    from app.services import chats as chat_service

    await chat_service.require_member(db, call.chat_id, actor.id)
    if call.status != "ringing":
        raise HTTPException(status.HTTP_409_CONFLICT, f"call is {call.status}, not ringing")
    call.status = "ended"
    call.ended_at = _now()
    await db.commit()
    await _publish_call(db, call, "call.rejected")
    await _write_call_system(db, call)
    return call


async def cancel_call(db: AsyncSession, *, actor: User, call_id: str) -> Call:
    """Direct: инициатор отменяет до accept — call.cancelled (§17)."""
    call = await get_call_checked(db, call_id)
    if call.initiator_id != actor.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only initiator can cancel")
    if call.status != "ringing":
        raise HTTPException(status.HTTP_409_CONFLICT, f"call is {call.status}, not ringing")
    call.status = "ended"
    call.ended_at = _now()
    await db.commit()
    await _publish_call(db, call, "call.cancelled")
    await _write_call_system(db, call)
    return call


async def join_call(db: AsyncSession, *, actor: User, call_id: str) -> Call:
    """Group: вход в комнату (первый join → active + started_at); call.joined (§17)."""
    call = await get_call_checked(db, call_id)
    from app.services import chats as chat_service

    await chat_service.require_member(db, call.chat_id, actor.id)
    if actor.is_bot:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bots do not make calls")
    if call.status == "ended":
        raise HTTPException(status.HTTP_409_CONFLICT, "call already ended")
    part = await db.get(CallParticipant, (call.id, actor.id))
    if part is None:
        db.add(CallParticipant(call_id=call.id, user_id=actor.id))
    elif part.left_at is not None:
        part.left_at = None
    if call.status == "ringing":
        call.status = "active"
        call.started_at = _now()
    await db.commit()
    await _publish_call(db, call, "call.joined", {"user_id": actor.id})
    return call


async def leave_call(db: AsyncSession, *, actor: User, call_id: str) -> Call:
    """Выход участника; call.left (§17).

    Direct 1:1 — выход одного завершает звонок для обоих (как Telegram):
    висящий «звонок» у собеседника при сбросе бессмысленен.
    Group — звонок живёт, пока не вышли все (последний → ended).
    """
    call = await get_call_checked(db, call_id)
    from app.services import chats as chat_service

    await chat_service.require_member(db, call.chat_id, actor.id)
    part = await db.get(CallParticipant, (call.id, actor.id))
    if part is not None and part.left_at is None:
        part.left_at = _now()

    chat = await db.get(Chat, call.chat_id)
    direct_done = chat is not None and chat.type == "direct" and call.status == "active"
    if direct_done or (call.status == "active" and not await _active_participants(db, call.id)):
        call.status = "ended"
        call.ended_at = _now()
        await db.commit()
        await _publish_call(db, call, "call.left", {"user_id": actor.id})
        await _write_call_system(db, call)
        return call
    await db.commit()
    await _publish_call(db, call, "call.left", {"user_id": actor.id})
    return call


async def _write_call_system(db: AsyncSession, call: Call) -> None:
    """System-сообщение о завершении звонка (§17): call_ended с длительностью / call_missed."""
    from app.services import messages as message_service

    duration_s: int | None = None
    if call.started_at and call.ended_at:
        started = call.started_at if call.started_at.tzinfo else call.started_at.replace(tzinfo=UTC)
        ended = call.ended_at if call.ended_at.tzinfo else call.ended_at.replace(tzinfo=UTC)
        duration_s = max(0, int((ended - started).total_seconds()))
    kind = "call_missed" if call.status == "ringing" or duration_s is None else "call_ended"
    payload: dict[str, Any] = {"call_id": call.id, "kind_of_call": call.kind, "initiator_id": call.initiator_id}
    if duration_s is not None:
        payload["duration_s"] = duration_s
    await message_service.create_system_message(
        db, chat_id=call.chat_id, kind=kind, payload=payload
    )


async def cleanup_stale_calls(db: AsyncSession, *, now: datetime | None = None) -> int:
    """ringing старше TTL → ended + call_missed (только direct — group открывается
    сразу active, §17 B); active без участников → ended (§17)."""
    now = now or _now()
    closed = 0
    stale_rings = (
        await db.scalars(
            select(Call)
            .join(Chat, Call.chat_id == Chat.id)
            .where(
                Chat.type == "direct",
                Call.status == "ringing",
                Call.created_at < datetime.fromtimestamp(now.timestamp() - CALL_TIMEOUT_SECONDS, tz=UTC),
            )
        )
    ).all()
    for call in stale_rings:
        call.status = "ended"
        call.ended_at = now
        closed += 1
    if stale_rings:
        await db.commit()
    for call in stale_rings:
        await _write_call_system(db, call)

    actives = (await db.scalars(select(Call).where(Call.status == "active"))).all()
    for call in actives:
        if not await _active_participants(db, call.id):
            call.status = "ended"
            call.ended_at = now
            closed += 1
            await db.commit()
            await _write_call_system(db, call)
    return closed
