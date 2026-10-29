import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from app.config import get_settings


@dataclass
class Connection:
    websocket: WebSocket
    user_id: uuid.UUID
    platform: str
    chat_ids: set[uuid.UUID] = field(default_factory=set)
    connected_at: float = field(default_factory=time.time)


class Hub:
    def __init__(self) -> None:
        self.connections: dict[uuid.UUID, list[Connection]] = {}
        self._lock = asyncio.Lock()

    async def add(self, connection: Connection) -> None:
        async with self._lock:
            self.connections.setdefault(connection.user_id, []).append(connection)

    async def remove(self, connection: Connection) -> None:
        async with self._lock:
            items = self.connections.get(connection.user_id, [])
            if connection in items:
                items.remove(connection)
            if not items:
                self.connections.pop(connection.user_id, None)

    def refresh_subscriptions(self, connection: Connection, chat_ids: set[uuid.UUID]) -> None:
        connection.chat_ids = chat_ids

    def local_for_chat(self, chat_id: uuid.UUID) -> list[Connection]:
        return [
            conn
            for conns in self.connections.values()
            for conn in conns
            if chat_id in conn.chat_ids
        ]

    def local_for_users(self, user_ids: list[uuid.UUID]) -> list[Connection]:
        return [
            conn for uid in user_ids for conn in self.connections.get(uid, [])
        ]

    def local_sharing_chats(self, chat_ids: set[uuid.UUID]) -> list[Connection]:
        targets = []
        for conns in self.connections.values():
            for conn in conns:
                if conn.chat_ids & chat_ids:
                    targets.append(conn)
        return targets

    def has_local(self, user_id: uuid.UUID) -> bool:
        return bool(self.connections.get(user_id))


hub = Hub()


async def listen_valkey() -> None:
    from app.core.valkey import get_valkey

    valkey = get_valkey()
    pubsub = valkey.pubsub()
    await pubsub.subscribe(get_settings().ws_event_channel)
    try:
        async for message in pubsub.listen():
            if message is None or message.get("type") != "message":
                continue
            raw = message.get("data")
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except (TypeError, ValueError):
                continue
            await route_event(event)
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(get_settings().ws_event_channel)
        await pubsub.aclose()


async def route_event(event: dict[str, Any]) -> None:
    event_type = event.get("type")
    payload = event.get("data", event)
    if event.get("user_ids"):
        targets = hub.local_for_users([uuid.UUID(u) for u in event["user_ids"]])
        await send_to(targets, event_type, payload)
        return
    chat_id = event.get("chat_id")
    if not chat_id:
        return
    try:
        cid = uuid.UUID(chat_id)
    except ValueError:
        return
    if event_type in ("typing.start", "typing.stop"):
        exclude = event.get("exclude_user_id")
        targets = [
            conn
            for conn in hub.local_for_chat(cid)
            if str(conn.user_id) != exclude
        ]
    elif event_type == "presence.update":
        user_chat_ids = {uuid.UUID(u) for u in event.get("user_chat_ids", [])}
        targets = hub.local_sharing_chats(user_chat_ids) if user_chat_ids else []
    else:
        targets = hub.local_for_chat(cid)
    await send_to(targets, event_type, payload)


async def send_to(connections: list[Connection], event_type: Any, payload: Any) -> None:
    frame = json.dumps({"type": event_type, "data": payload}, ensure_ascii=False, default=str)
    results = await asyncio.gather(
        *(conn.websocket.send_text(frame) for conn in connections),
        return_exceptions=True,
    )
    for conn, result in zip(connections, results, strict=False):
        if isinstance(result, Exception):
            await hub.remove(conn)
