"""Тесты realtime: tickets, read receipts, envelope, presence, WS-handshake (§5, §9, §12).

Valkey подменяется фейком (in-memory); WS — юнит-уровень handshake,
fanout — через публикации фейка.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
from app.api.deps import current_user
from app.core import valkey as valkey_core
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.services import realtime as rt
from app.services.users import upsert_user_by_sub
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# --- Fake Valkey (in-memory) ---


class FakeValkey:
    """Минимальный фейк: set/get/getdel/incr/decr/expire/delete/publish."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def getdel(self, key: str) -> str | None:
        return self.store.pop(key, None)

    async def incr(self, key: str) -> int:
        self.store[key] = str(int(self.store.get(key, "0")) + 1)
        return int(self.store[key])

    async def decr(self, key: str) -> int:
        self.store[key] = str(int(self.store.get(key, "0")) - 1)
        return int(self.store[key])

    async def expire(self, key: str, ttl: int) -> None:
        pass  # TTL не тикает в фейке

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self.store.pop(k, None)

    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1

    async def aclose(self) -> None:
        pass


@pytest.fixture
def fake_valkey(monkeypatch: pytest.MonkeyPatch) -> FakeValkey:
    fake = FakeValkey()
    monkeypatch.setattr(valkey_core, "get_valkey", lambda: fake)
    monkeypatch.setattr(valkey_core, "_client", None)
    return fake


# --- DB + auth fixture (паттерн test_chats) ---


@pytest.fixture
async def db(fake_valkey: FakeValkey) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with maker() as session:
        yield session
    app.dependency_overrides.clear()
    await engine.dispose()


@dataclass
class Actors:
    """Тестовые пользователи + переключатель текущего."""

    alice: User
    bob: User

    def act_as(self, name: str) -> None:
        target: User = getattr(self, name)

        def _override() -> User:
            return target

        app.dependency_overrides[current_user] = _override


@pytest.fixture
async def actors(db: AsyncSession) -> Actors:
    a = Actors(
        alice=await upsert_user_by_sub(db, sub="sub-a", preferred_username="alice"),
        bob=await upsert_user_by_sub(db, sub="sub-b", preferred_username="bob"),
    )
    a.act_as("alice")
    return a


async def ac() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def make_chat(db: AsyncSession, actors: Actors, *members: str) -> str:
    from app.services.chats import create_group

    chat = await create_group(
        db,
        creator_id=actors.alice.id,
        title="T",
        member_ids=[getattr(actors, m).id for m in members],
    )
    return chat.id


# --- Tickets (§5, §9) ---


@pytest.mark.asyncio
async def test_ticket_one_time(db: AsyncSession, actors: Actors, fake_valkey: FakeValkey) -> None:
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post("/api/v1/ws/ticket")
        assert r.status_code == 201, r.text
        ticket = r.json()["ticket"]

        # одноразовость: первое потребление — user_id, второе — None
        consumed = await rt.consume_ws_ticket(ticket)
        assert consumed == actors.alice.id
        assert await rt.consume_ws_ticket(ticket) is None


@pytest.mark.asyncio
async def test_ticket_unknown_ticket_returns_none(db: AsyncSession, actors: Actors) -> None:
    assert await rt.consume_ws_ticket("no-such-ticket") is None


# --- Envelope (§9) ---


@pytest.mark.asyncio
async def test_envelope_shape() -> None:
    raw = rt.envelope("message.new", {"id": "x"})
    evt = json.loads(raw)
    assert evt["type"] == "message.new"
    assert evt["data"] == {"id": "x"}
    assert "event_id" in evt and "ts" in evt


# --- Read receipts (§9, §12) ---


@pytest.mark.asyncio
async def test_read_cursor_moves_forward_only(
    db: AsyncSession, actors: Actors, fake_valkey: FakeValkey
) -> None:
    from app.models.chat import ChatMember
    from app.models.message import Message

    chat_id = await make_chat(db, actors, "bob")
    m1 = Message(id="01900000-0000-7000-8000-00000000000a", chat_id=chat_id, sender_id=actors.alice.id, type="text", text="1")
    m2 = Message(id="01900000-0000-7000-8000-00000000000b", chat_id=chat_id, sender_id=actors.alice.id, type="text", text="2")
    db.add_all([m1, m2])
    await db.commit()

    actors.act_as("bob")
    async with await ac() as c:
        r1 = await c.post(f"/api/v1/chats/{chat_id}/read", json={"message_id": m2.id})
        assert r1.status_code == 204, r1.text

        # откат назад — курсор не двигается (§12)
        r2 = await c.post(f"/api/v1/chats/{chat_id}/read", json={"message_id": m1.id})
        assert r2.status_code == 204

        cursor = await db.get(ChatMember, (chat_id, actors.bob.id))
        assert cursor is not None
        assert cursor.last_read_message_id == m2.id

        # событие read опубликовано
        assert any(ch == f"chat:{chat_id}" for ch, _ in fake_valkey.published)


@pytest.mark.asyncio
async def test_read_foreign_message_422(
    db: AsyncSession, actors: Actors, fake_valkey: FakeValkey
) -> None:
    from app.models.message import Message

    chat_id = await make_chat(db, actors, "bob")
    other_chat = await make_chat(db, actors, "bob")
    foreign = Message(
        id="01900000-0000-7000-8000-00000000000c", chat_id=other_chat, sender_id=actors.alice.id, type="text", text="x"
    )
    db.add(foreign)
    await db.commit()

    actors.act_as("bob")
    async with await ac() as c:
        r = await c.post(f"/api/v1/chats/{chat_id}/read", json={"message_id": foreign.id})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_read_non_member_403(db: AsyncSession, actors: Actors) -> None:
    """Неучастник не может двигать курсор: require_member → 403; чужое сообщение → 422."""
    from app.models.message import Message

    # сообщение в чужом для alice чате (bob — владелец и единственный участник)
    from app.services.chats import create_group

    foreign_chat = await create_group(db, creator_id=actors.bob.id, title="X", member_ids=[actors.bob.id])
    m = Message(
        id="01900000-0000-7000-8000-00000000000d",
        chat_id=foreign_chat.id,
        sender_id=actors.bob.id,
        type="text",
        text="x",
    )
    db.add(m)
    await db.commit()

    # bob — участник foreign_chat: движение курсора на m — ок (204)
    actors.act_as("bob")
    async with await ac() as c:
        r = await c.post(f"/api/v1/chats/{foreign_chat.id}/read", json={"message_id": m.id})
        assert r.status_code == 204, r.text

    # alice не участник foreign_chat → 403
    actors.act_as("alice")
    async with await ac() as c:
        r2 = await c.post(f"/api/v1/chats/{foreign_chat.id}/read", json={"message_id": m.id})
        assert r2.status_code == 403


# --- Presence (§9) ---


@pytest.mark.asyncio
async def test_presence_counter(db: AsyncSession, actors: Actors, fake_valkey: FakeValkey) -> None:
    uid = actors.alice.id
    assert await valkey_core.presence_connect(uid) == 1
    assert await valkey_core.presence_connect(uid) == 2  # две вкладки (§9)
    assert await valkey_core.presence_disconnect(uid) == 1
    assert await valkey_core.presence_disconnect(uid) == 0
    # счётчик обнулён и удалён из Valkey
    assert "presence:" + uid not in fake_valkey.store


# --- message.* события публикуются (§9) ---


@pytest.mark.asyncio
async def test_send_publishes_message_new(
    db: AsyncSession, actors: Actors, fake_valkey: FakeValkey
) -> None:
    chat_id = await make_chat(db, actors, "bob")
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post(f"/api/v1/chats/{chat_id}/messages", json={"text": "привет"})
        assert r.status_code == 201
        events = [json.loads(payload) for ch, payload in fake_valkey.published if ch == f"chat:{chat_id}"]
        mine = [e for e in events if e["type"] == "message.new"]
        assert mine and all("message" in e["data"] and "id" in e["data"]["message"] for e in mine)
        assert any(
            e["data"]["message"]["id"] == r.json()["id"]
            and e["data"]["message"]["text"] == "привет"
            and "reactions" in e["data"]["message"]  # полная сериализация (§9, этап 10.2)
            for e in mine
        )


@pytest.mark.asyncio
async def test_edit_delete_publish_events(
    db: AsyncSession, actors: Actors, fake_valkey: FakeValkey
) -> None:
    chat_id = await make_chat(db, actors, "bob")
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post(f"/api/v1/chats/{chat_id}/messages", json={"text": "x"})
        mid = r.json()["id"]

        fake_valkey.published.clear()
        await c.patch(f"/api/v1/messages/{mid}", json={"text": "y"})
        types = [json.loads(p)["type"] for _, p in fake_valkey.published]
        assert "message.edited" in types

        fake_valkey.published.clear()
        await c.delete(f"/api/v1/messages/{mid}")
        types = [json.loads(p)["type"] for _, p in fake_valkey.published]
        assert "message.deleted" in types


# --- WS-handshake: ticket-аутентификация (§5) ---


def _ws_scope(query_string: bytes = b"") -> dict[str, Any]:
    """Минимальный ASGI-scope для вызова ws_current_user в тестах."""
    return {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "query_string": query_string,
        "headers": [],
    }


async def _send(message: Any) -> None:
    pass


def _recv_msg() -> Any:
    return {"type": "websocket.disconnect"}


_recv = _recv_msg  # alias под ASGI-имя


@pytest.mark.asyncio
async def test_ws_rejects_missing_ticket(db: AsyncSession, actors: Actors) -> None:
    """WS-handshake без ticket → WebSocketException 4401 (§5)."""
    from app.api.v1.realtime import ws_current_user
    from fastapi.exceptions import WebSocketException
    from starlette.websockets import WebSocket as StarletteWebSocket

    with pytest.raises(WebSocketException) as exc_info:
        await ws_current_user(StarletteWebSocket(_ws_scope(), _recv, _send), db)
    assert exc_info.value.code == 4401


@pytest.mark.asyncio
async def test_ws_rejects_used_ticket(
    db: AsyncSession, actors: Actors, fake_valkey: FakeValkey
) -> None:
    """Повторное использование ticket — отвергается (одноразовость GETDEL, §5)."""
    from app.api.v1.realtime import ws_current_user
    from fastapi.exceptions import WebSocketException
    from starlette.websockets import WebSocket as StarletteWebSocket

    ticket = await rt.create_ws_ticket(actors.bob.id)
    # первое потребление — ок
    assert await rt.consume_ws_ticket(ticket) == actors.bob.id

    qs = f"ticket={ticket}".encode()
    with pytest.raises(WebSocketException) as exc_info:
        await ws_current_user(StarletteWebSocket(_ws_scope(qs), _recv, _send), db)
    assert exc_info.value.code == 4401


@pytest.mark.asyncio
async def test_ticket_for_missing_user_403(
    db: AsyncSession, actors: Actors, fake_valkey: FakeValkey
) -> None:
    """Ticket указывает на несуществующего/неактивного пользователя → 4403."""
    from app.api.v1.realtime import ws_current_user
    from fastapi.exceptions import WebSocketException
    from starlette.websockets import WebSocket as StarletteWebSocket

    ticket = await rt.create_ws_ticket("ghost-user")
    qs = f"ticket={ticket}".encode()
    with pytest.raises(WebSocketException) as exc_info:
        await ws_current_user(StarletteWebSocket(_ws_scope(qs), _recv, _send), db)
    assert exc_info.value.code == 4403
