"""Звонки: REST-роуты (Docs/concept.md §12, §17).

Все мутации — REST; WS — только уведомления call.* (§9). Room-токен —
скоупед JWT LiveKit (§17); LiveKit не сконфигурирован → 503 на token.
"""

from typing import Annotated

from app.api.deps import UserDep
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.call import CallCreateIn, CallOut, CallTokenOut
from app.services import calls as call_service
from app.services.calls_tokens import LiveKitNotConfigured, issue_room_token
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["calls"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.post("/calls", response_model=CallOut, status_code=201)
async def start_call(body: CallCreateIn, me: UserDep, db: DbDep) -> CallOut:
    """Создание звонка (§17): direct — ringing, group — ringing (join-модель)."""
    call, _created = await call_service.start_call(db, actor=me, chat_id=body.chat_id, kind=body.kind)
    return CallOut.model_validate(await call_service.get_call_out(db, call))


@router.post("/calls/{call_id}/accept", response_model=CallOut)
async def accept_call(call_id: str, me: UserDep, db: DbDep) -> CallOut:
    """Direct: ответил — active (§17)."""
    call = await call_service.accept_call(db, actor=me, call_id=call_id)
    return CallOut.model_validate(await call_service.get_call_out(db, call))


@router.post("/calls/{call_id}/reject", response_model=CallOut)
async def reject_call(call_id: str, me: UserDep, db: DbDep) -> CallOut:
    """Direct: отказался — ended + call_missed (§17)."""
    call = await call_service.reject_call(db, actor=me, call_id=call_id)
    return CallOut.model_validate(await call_service.get_call_out(db, call))


@router.post("/calls/{call_id}/cancel", response_model=CallOut)
async def cancel_call(call_id: str, me: UserDep, db: DbDep) -> CallOut:
    """Direct: инициатор отменил до accept — ended (§17)."""
    call = await call_service.cancel_call(db, actor=me, call_id=call_id)
    return CallOut.model_validate(await call_service.get_call_out(db, call))


@router.post("/calls/{call_id}/join", response_model=CallOut)
async def join_call(call_id: str, me: UserDep, db: DbDep) -> CallOut:
    """Group: вход в комнату (первый join → active); также повторный вход (§17)."""
    call = await call_service.join_call(db, actor=me, call_id=call_id)
    return CallOut.model_validate(await call_service.get_call_out(db, call))


@router.post("/calls/{call_id}/leave", response_model=CallOut)
async def leave_call(call_id: str, me: UserDep, db: DbDep) -> CallOut:
    """Выход; последний вышел — ended + system-сообщение (§17)."""
    call = await call_service.leave_call(db, actor=me, call_id=call_id)
    return CallOut.model_validate(await call_service.get_call_out(db, call))


@router.post("/calls/{call_id}/token", response_model=CallTokenOut)
async def call_token(call_id: str, me: UserDep, db: DbDep) -> CallTokenOut:
    """Room-токен LiveKit (§17): только участник звонка; TTL ~10 мин."""
    call = await call_service.get_call_checked(db, call_id)
    from app.services import chats as chat_service

    await chat_service.require_member(db, call.chat_id, me.id)
    parts = await call_service._active_participants(db, call.id)
    if call.status == "ended" or (call.status == "ringing" and me.id not in {p.user_id for p in parts}):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not a call participant")
    try:
        token = issue_room_token(user_id=me.id, room=call.id)
    except LiveKitNotConfigured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "calls are not configured") from None
    return CallTokenOut(token=token, ws_url=get_settings().livekit_ws_url)
