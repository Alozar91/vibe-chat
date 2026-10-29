import json
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.config import get_settings
from app.core.errors import forbidden
from app.core.security import AuthContext, verify_access_token
from app.core.valkey import get_valkey
from app.db.session import session_factory
from app.models import ChatMember, ChatMemberStatus, UserKind, UserRole, UserStatus
from app.modules.auth import sessions as session_store
from app.modules.auth.dependencies import authenticate_bot_token
from app.modules.realtime.hub import Connection, hub
from app.modules.users.cache import get_auth_info

router = APIRouter(tags=["realtime"])

PRESENCE_PREFIX = "presence:"


async def _auth_websocket(websocket: WebSocket) -> AuthContext:
    token = websocket.query_params.get("access_token")
    async with session_factory() as db:
        if token:
            if token.startswith("mt_"):
                return await authenticate_bot_token(db, token)
            claims = await verify_access_token(token)
            user_id = uuid.UUID(claims["sub"])
            valkey = get_valkey()
            info = await get_auth_info(db, valkey, user_id)
            if info["status"] != "active":
                raise forbidden("Учётная запись отключена")
            return AuthContext(
                user_id=user_id,
                kind=UserKind(info["kind"]),
                role=UserRole(info["role"]),
                status=UserStatus(info["status"]),
                via="bearer",
            )
        sid = websocket.cookies.get(get_settings().session_cookie_name)
        if sid:
            data = await session_store.get_session_data(get_valkey(), sid)
            if data:
                user_id = uuid.UUID(data["user_id"])
                info = await get_auth_info(db, get_valkey(), user_id)
                if info["status"] != "active":
                    raise forbidden("Учётная запись отключена")
                return AuthContext(
                    user_id=user_id,
                    kind=UserKind(info["kind"]),
                    role=UserRole(info["role"]),
                    status=UserStatus(info["status"]),
                    via="cookie",
                    session_id=sid,
                )
    raise forbidden("Требуется авторизация")


async def _member_chat_ids(db, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = (
        await db.scalars(
            select(ChatMember.chat_id).where(
                ChatMember.user_id == user_id, ChatMember.status == ChatMemberStatus.ACTIVE
            )
        )
    ).all()
    return set(rows)


async def _publish(event: dict) -> None:
    await get_valkey().publish(
        get_settings().ws_event_channel, json.dumps(event, ensure_ascii=False, default=str)
    )


async def _presence_online(user_id: uuid.UUID, chat_ids: set[uuid.UUID]) -> None:
    valkey = get_valkey()
    await valkey.set(PRESENCE_PREFIX + str(user_id), "1", ex=60)
    user_chat_ids = [str(cid) for cid in chat_ids]
    await _publish({"type": "presence.update", "user_id": str(user_id), "online": True, "user_chat_ids": user_chat_ids})


async def _presence_offline(user_id: uuid.UUID, chat_ids: set[uuid.UUID]) -> None:
    valkey = get_valkey()
    if not hub.has_local(user_id):
        await valkey.delete(PRESENCE_PREFIX + str(user_id))
    user_chat_ids = [str(cid) for cid in chat_ids]
    await _publish({"type": "presence.update", "user_id": str(user_id), "online": False, "user_chat_ids": user_chat_ids})


async def _user_ids_sharing(chat_id: uuid.UUID) -> set[uuid.UUID]:
    async with session_factory() as db:
        rows = (
            await db.scalars(
                select(ChatMember.user_id).where(
                    ChatMember.chat_id == chat_id, ChatMember.status == ChatMemberStatus.ACTIVE
                )
            )
        ).all()
        return set(rows)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    access_token: str | None = Query(default=None),
) -> None:
    try:
        ctx = await _auth_websocket(websocket)
    except Exception:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    connection = Connection(websocket=websocket, user_id=ctx.user_id, platform=ctx.via)
    await hub.add(connection)
    async with session_factory() as db:
        chat_ids = await _member_chat_ids(db, ctx.user_id)
    hub.refresh_subscriptions(connection, chat_ids)
    await _presence_online(ctx.user_id, chat_ids)
    valkey = get_valkey()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            msg_type = message.get("type")
            if msg_type == "ping":
                await valkey.set(PRESENCE_PREFIX + str(ctx.user_id), "1", ex=60)
                await websocket.send_text(json.dumps({"type": "pong", "data": {}}))
            elif msg_type in ("typing.start", "typing.stop"):
                chat_id = message.get("chat_id")
                try:
                    cid = uuid.UUID(chat_id)
                except (TypeError, ValueError):
                    continue
                if cid in connection.chat_ids:
                    await _publish(
                        {
                            "type": msg_type,
                            "chat_id": str(cid),
                            "exclude_user_id": str(ctx.user_id),
                            "data": {"chat_id": str(cid), "user_id": str(ctx.user_id)},
                        }
                    )
            elif msg_type == "subscribe.refresh":
                async with session_factory() as db:
                    chat_ids = await _member_chat_ids(db, ctx.user_id)
                hub.refresh_subscriptions(connection, chat_ids)
            elif msg_type == "sync.request":
                await _handle_sync(websocket, message)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.remove(connection)
        await _presence_offline(ctx.user_id, connection.chat_ids)


async def _handle_sync(websocket: WebSocket, message: dict) -> None:
    from app.models import Message

    chats = message.get("chats") or []
    if not isinstance(chats, list):
        return
    for item in chats[:100]:
        try:
            chat_id = uuid.UUID(str(item.get("chat_id")))
            last_seq = int(item.get("last_seq", 0))
        except (TypeError, ValueError):
            continue
        async with session_factory() as db:
            rows = (
                await db.scalars(
                    select(Message)
                    .where(Message.chat_id == chat_id, Message.seq > last_seq)
                    .order_by(Message.seq.asc())
                    .limit(200)
                )
            ).all()
            for msg in rows:
                frame = json.dumps(
                    {
                        "type": "message.new",
                        "chat_id": str(chat_id),
                        "data": {
                            "chat_id": str(msg.chat_id),
                            "seq": msg.seq,
                            "sender_id": str(msg.sender_id),
                            "type": str(msg.type),
                            "body": "" if msg.deleted_at else msg.body,
                            "reply_to_seq": msg.reply_to_seq,
                            "created_at": msg.created_at.isoformat(),
                        },
                    },
                    ensure_ascii=False,
                    default=str,
                )
                await websocket.send_text(frame)
