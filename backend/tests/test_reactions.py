"""Тесты реакций (§6, §12): toggle, фиксированный набор, права, WS-событие, сериализация."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from app.api.deps import current_user
from app.core import valkey as valkey_core
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.message import Message
from app.models.user import User
from app.services import reactions as reaction_service
from app.services.chats import create_group
from app.services.users import upsert_user_by_sub
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class FakeValkey:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}

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
        pass

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self.store.pop(k, None)

    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1

    async def aclose(self) -> None:
        pass


@pytest.fixture
def vk(monkeypatch: pytest.MonkeyPatch) -> FakeValkey:
    fake = FakeValkey()
    monkeypatch.setattr(valkey_core, "get_valkey", lambda: fake)
    monkeypatch.setattr(valkey_core, "_client", None)
    return fake


@pytest.fixture
async def db(vk: FakeValkey) -> AsyncIterator[AsyncSession]:
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


async def make_chat_with_message(db: AsyncSession, actors: Actors) -> tuple[str, Message]:
    """Групповой чат alice+bob с одним сообщением от alice."""
    chat = await create_group(
        db, creator_id=actors.alice.id, title="T", member_ids=[actors.bob.id]
    )
    m = Message(
        id="01900000-0000-7000-8000-00000000000a",
        chat_id=chat.id,
        sender_id=actors.alice.id,
        type="text",
        text="привет",
        client_ref="ref-1",
    )
    db.add(m)
    await db.commit()
    return chat.id, m


# --- Toggle-семантика (§6) ---


@pytest.mark.asyncio
async def test_reaction_put_toggle_cycle(db: AsyncSession, actors: Actors, vk: FakeValkey) -> None:
    _chat_id, m = await make_chat_with_message(db, actors)
    actors.act_as("bob")
    async with await ac() as c:
        # поставить
        r1 = await c.put(f"/api/v1/messages/{m.id}/reactions", json={"emoji": "thumbs_up"})
        assert r1.status_code == 200, r1.text
        assert r1.json() == [{"emoji": "thumbs_up", "user_ids": [actors.bob.id]}]

        # повторный PUT той же — снять (toggle, §6)
        r2 = await c.put(f"/api/v1/messages/{m.id}/reactions", json={"emoji": "thumbs_up"})
        assert r2.status_code == 200
        assert r2.json() == []

        # снова поставить, затем заменить на другую
        await c.put(f"/api/v1/messages/{m.id}/reactions", json={"emoji": "thumbs_up"})
        r3 = await c.put(f"/api/v1/messages/{m.id}/reactions", json={"emoji": "heart"})
        assert r3.json() == [{"emoji": "heart", "user_ids": [actors.bob.id]}]  # замена, не +1

        # одна реакция на пользователя: count = 1 (составной PK)
        assert await reaction_service.count_reactions(db, [m.id]) == 1


@pytest.mark.asyncio
async def test_reaction_multiple_users_grouped(db: AsyncSession, actors: Actors) -> None:
    """Разные пользователи ставят один emoji → одна группа со списком user_ids (§6)."""
    chat_id, m = await make_chat_with_message(db, actors)
    actors.act_as("alice")
    async with await ac() as c:
        await c.put(f"/api/v1/messages/{m.id}/reactions", json={"emoji": "fire"})
    actors.act_as("bob")
    async with await ac() as c:
        r = await c.put(f"/api/v1/messages/{m.id}/reactions", json={"emoji": "fire"})
        got = r.json()
        assert len(got) == 1 and got[0]["emoji"] == "fire"
        # порядок user_ids при равных created_at не гарантирован — сравниваем множеством
        assert set(got[0]["user_ids"]) == {actors.alice.id, actors.bob.id}

        # у каждого ровно одна реакция на сообщение (составной PK)
        assert await reaction_service.count_reactions(db, [m.id]) == 2

        # и в ленте сгруппировано так же
        r2 = await c.get(f"/api/v1/chats/{chat_id}/messages")
        found = [msg for msg in r2.json() if msg["id"] == m.id]
        assert len(found[0]["reactions"]) == 1
        assert set(found[0]["reactions"][0]["user_ids"]) == {actors.alice.id, actors.bob.id}


# --- Ограничения (§6) ---


@pytest.mark.asyncio
async def test_reaction_unknown_emoji_422(db: AsyncSession, actors: Actors) -> None:
    _chat_id, m = await make_chat_with_message(db, actors)
    actors.act_as("bob")
    async with await ac() as c:
        r = await c.put(f"/api/v1/messages/{m.id}/reactions", json={"emoji": "clown"})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_reaction_system_message_422(db: AsyncSession, actors: Actors) -> None:
    chat_id, _m = await make_chat_with_message(db, actors)
    system = Message(
        id="01900000-0000-7000-8000-00000000000b",
        chat_id=chat_id,
        sender_id=None,
        type="system",
        text="чат создан",
        payload={"event": "chat.created"},
    )
    db.add(system)
    await db.commit()

    actors.act_as("alice")
    async with await ac() as c:
        r = await c.put(f"/api/v1/messages/{system.id}/reactions", json={"emoji": "check"})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_reaction_deleted_message_422(db: AsyncSession, actors: Actors) -> None:
    _chat_id, m = await make_chat_with_message(db, actors)
    from datetime import UTC, datetime

    m.deleted_at = datetime.now(UTC)
    await db.commit()

    actors.act_as("bob")
    async with await ac() as c:
        r = await c.put(f"/api/v1/messages/{m.id}/reactions", json={"emoji": "heart"})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_reaction_non_member_403(db: AsyncSession, actors: Actors) -> None:
    """Не-участник чата не может реагировать (§6 — только участники)."""
    # чат только alice; bob не участник
    from app.services.chats import create_group as cg

    solo_chat = await cg(db, creator_id=actors.alice.id, title="S", member_ids=[])
    m = Message(
        id="01900000-0000-7000-8000-00000000000c",
        chat_id=solo_chat.id,
        sender_id=actors.alice.id,
        type="text",
        text="x",
    )
    db.add(m)
    await db.commit()

    actors.act_as("bob")
    async with await ac() as c:
        r = await c.put(f"/api/v1/messages/{m.id}/reactions", json={"emoji": "heart"})
        assert r.status_code == 403


# --- WS-событие reaction.updated (§9) ---


@pytest.mark.asyncio
async def test_reaction_publishes_event(db: AsyncSession, actors: Actors, vk: FakeValkey) -> None:
    chat_id, m = await make_chat_with_message(db, actors)
    actors.act_as("bob")
    async with await ac() as c:
        await c.put(f"/api/v1/messages/{m.id}/reactions", json={"emoji": "laugh"})

    events = [
        json.loads(p)
        for ch, p in vk.published
        if ch == f"chat:{chat_id}"
    ]
    reaction_events = [e for e in events if e["type"] == "reaction.updated"]
    assert len(reaction_events) == 1
    data = reaction_events[0]["data"]
    assert data["message_id"] == m.id
    assert data["reactions"] == [{"emoji": "laugh", "user_ids": [actors.bob.id]}]


# --- Реакции в сериализации сообщений (§6) ---


@pytest.mark.asyncio
async def test_reactions_embedded_in_message_list(db: AsyncSession, actors: Actors) -> None:
    chat_id, m = await make_chat_with_message(db, actors)
    actors.act_as("bob")
    async with await ac() as c:
        await c.put(f"/api/v1/messages/{m.id}/reactions", json={"emoji": "check"})

        r = await c.get(f"/api/v1/chats/{chat_id}/messages")
        assert r.status_code == 200
        found = [msg for msg in r.json() if msg["id"] == m.id]
        assert found[0]["reactions"] == [{"emoji": "check", "user_ids": [actors.bob.id]}]


@pytest.mark.asyncio
async def test_reactions_hidden_on_deleted_message(db: AsyncSession, actors: Actors) -> None:
    """Удалённое сообщение: заглушка без реакций; строки reactions не удаляются (§6)."""
    chat_id, m = await make_chat_with_message(db, actors)
    actors.act_as("bob")
    async with await ac() as c:
        await c.put(f"/api/v1/messages/{m.id}/reactions", json={"emoji": "heart"})

    actors.act_as("alice")
    async with await ac() as c:
        await c.delete(f"/api/v1/messages/{m.id}")

    # строки остались в БД (§6 — надгробие скрывает, не удаляет)
    assert await reaction_service.count_reactions(db, [m.id]) == 1

    actors.act_as("bob")
    async with await ac() as c:
        r = await c.get(f"/api/v1/chats/{chat_id}/messages")
        deleted = [msg for msg in r.json() if msg["id"] == m.id][0]
        assert deleted["deleted_at"] is not None
        assert deleted["reactions"] == []


@pytest.mark.asyncio
async def test_reactions_not_in_updated_after_delta(db: AsyncSession, actors: Actors) -> None:
    """Реакция не двигает messages.updated_at (§6): дельта edit/delete её не отдаёт."""
    chat_id, m = await make_chat_with_message(db, actors)
    before_updated = m.updated_at

    actors.act_as("bob")
    async with await ac() as c:
        await c.put(f"/api/v1/messages/{m.id}/reactions", json={"emoji": "fire"})

    # свежий SELECT той же сессией (expire_all + get ломается greenlet'ом в aiosqlite)
    from sqlalchemy import select

    m2 = (await db.execute(select(Message).where(Message.id == m.id))).scalar_one()
    assert m2.updated_at == before_updated  # не двигался
    _ = chat_id
