"""WS /ws?ticket= и REST-роуты realtime: /ws/ticket, /chats/{id}/read (§9, §12)."""

import asyncio
import contextlib
import json
from typing import Annotated, Any

from app.api.deps import UserDep
from app.core import valkey
from app.db.session import get_db
from app.models.chat import ChatMember
from app.models.user import User
from app.schemas.chat import ReadIn
from app.services import realtime as rt
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.exceptions import WebSocketException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["realtime"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.post("/ws/ticket", status_code=201)
async def issue_ticket(me: UserDep) -> dict[str, str]:
    """Одноразовый ticket для WS-подключения (§5): TTL 30 сек, GETDEL при использовании."""
    ticket = await rt.create_ws_ticket(me.id)
    return {"ticket": ticket}


@router.post("/chats/{chat_id}/read", status_code=204)
async def mark_read(chat_id: str, body: ReadIn, me: UserDep, db: DbDep) -> None:
    """Курсор прочтения: только вперёд (MAX); событие `read` участникам (§9)."""
    await rt.mark_read(db, chat_id=chat_id, user_id=me.id, message_id=body.message_id)


async def ws_current_user(
    websocket: WebSocket,
    db: DbDep,
) -> User:
    """WS-аутентификация: одноразовый ticket → User (§5).

    Зависимость — работает и в тестах (override get_db / ws_current_user).
    """
    ticket = websocket.query_params.get("ticket")
    if not ticket:
        raise WebSocketException(code=4401, reason="missing ticket")
    user_id = await rt.consume_ws_ticket(ticket)
    if user_id is None:
        raise WebSocketException(code=4401, reason="invalid or used ticket")
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise WebSocketException(code=4403, reason="inactive user")
    return user


WsUserDep = Annotated[User, Depends(ws_current_user)]


async def _pump_pubsub(pubsub: Any, websocket: WebSocket) -> None:
    """Читает Pub/Sub и пересылает в WS до отмены задачи."""
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is not None and message.get("type") == "message":
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="ignore")
                if isinstance(data, str):
                    await websocket.send_text(data)  # конверт готов — отправляем как есть (§9)
            await asyncio.sleep(0)
    except (asyncio.CancelledError, WebSocketDisconnect, Exception):
        pass


async def _ws_receive_loop(user: User, chat_ids: set[str], websocket: WebSocket) -> None:
    """Client→server: только `typing` (§9). Незнакомые типы игнорируются — соединение живёт."""
    while True:
        raw = await websocket.receive_text()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue  # битый JSON — игнор
        if payload.get("type") == "typing":
            chat_id = (payload.get("data") or {}).get("chat_id", "")
            if chat_id in chat_ids:
                await rt.publish_to_chat(chat_id, "typing", {"chat_id": chat_id, "user_id": user.id})


async def _notify_chatmates(db: AsyncSession, user: User, *, online: bool) -> None:
    """presence (§9) соседям по чатам: user:{id} каждого, без самого пользователя.

    Прежняя реализация публиковала presence в собственный канал — онлайн-статус
    не видел никто, кроме самого пользователя (этап 10.2).
    """
    mate_ids = set(
        (
            await db.execute(
                select(ChatMember.user_id)
                .where(
                    ChatMember.chat_id.in_(
                        select(ChatMember.chat_id).where(ChatMember.user_id == user.id)
                    ),
                    ChatMember.user_id != user.id,
                )
            )
        )
        .scalars()
        .all()
    )
    payload = {
        "user_id": user.id,
        "online": online,
        "last_seen_at": user.last_seen_at.isoformat() if user.last_seen_at else None,
    }
    for uid in mate_ids:
        await rt.publish_to_user(uid, "presence", payload)


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, user: WsUserDep, db: DbDep) -> None:
    await websocket.accept()

    chat_ids = set(
        (await db.execute(select(ChatMember.chat_id).where(ChatMember.user_id == user.id)))
        .scalars()
        .all()
    )

    channels = [f"user:{user.id}"] + [f"chat:{cid}" for cid in chat_ids]
    pubsub = await valkey.subscribe_channels(*channels)
    await valkey.presence_connect(user.id)
    # presence (§9) — «соседям по чатам» (в user:{id} каждого), не себе: онлайн-статус
    # виден в шапке чата и у списка. offline — только когда закрыта последняя вкладка.
    await _notify_chatmates(db, user, online=True)

    pubsub_task = asyncio.create_task(_pump_pubsub(pubsub, websocket))
    receive_task = asyncio.create_task(_ws_receive_loop(user, chat_ids, websocket))

    try:
        # гонка задач: падение любой закрывает соединение
        _done, pending = await asyncio.wait(
            {pubsub_task, receive_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
    finally:
        pubsub_task.cancel()
        receive_task.cancel()
        await valkey.presence_disconnect(user.id)
        remaining = await valkey.get_valkey().get(f"presence:{user.id}")
        if remaining is None or int(remaining) <= 0:
            from app.core.valkey import set_last_seen_if_offline

            await set_last_seen_if_offline(db, user.id)
            await db.refresh(user)
            await _notify_chatmates(db, user, online=False)
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe()
            await pubsub.aclose()
        with contextlib.suppress(Exception):
            await websocket.close()  # уже закрыт клиентом — норма
