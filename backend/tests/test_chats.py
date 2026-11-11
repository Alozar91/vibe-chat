"""Тесты чатов: direct/group создание, права, идемпотентность (§6, §12).

Auth подменяется dependency_overrides на локальных пользователей без Keycloak.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from app.api.deps import current_user
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.services.users import upsert_user_by_sub
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@dataclass
class Actors:
    """Тестовые пользователи + переключатель текущего."""

    alice: User
    bob: User
    carol: User

    def act_as(self, name: str) -> None:
        target: User = getattr(self, name)

        def _override() -> User:
            return target

        app.dependency_overrides[current_user] = _override


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
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


@pytest.fixture
async def actors(db: AsyncSession) -> Actors:
    a = Actors(
        alice=await upsert_user_by_sub(db, sub="sub-a", preferred_username="alice"),
        bob=await upsert_user_by_sub(db, sub="sub-b", preferred_username="bob"),
        carol=await upsert_user_by_sub(db, sub="sub-c", preferred_username="carol"),
    )
    a.act_as("alice")
    return a


async def ac() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_direct_create_and_reuse(db: AsyncSession, actors: Actors) -> None:
    async with await ac() as c:
        r1 = await c.post("/api/v1/chats/direct", json={"user_id": actors.bob.id})
        assert r1.status_code == 201, r1.text
        assert r1.json()["created"] is True
        chat_id = r1.json()["chat_id"]

        r2 = await c.post("/api/v1/chats/direct", json={"user_id": actors.bob.id})
        assert r2.status_code == 201
        assert r2.json() == {"chat_id": chat_id, "created": False}


@pytest.mark.asyncio
async def test_direct_self_chat_422(db: AsyncSession, actors: Actors) -> None:
    async with await ac() as c:
        r = await c.post("/api/v1/chats/direct", json={"user_id": actors.alice.id})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_direct_duplicate_key_protection(db: AsyncSession, actors: Actors) -> None:
    """Прямая проверка direct_chat_keys: пара даёт ровно один чат (§6)."""
    from app.services.chats import create_or_get_direct

    chat1, created1 = await create_or_get_direct(db, me_id=actors.alice.id, other_id=actors.bob.id)
    chat2, created2 = await create_or_get_direct(db, me_id=actors.bob.id, other_id=actors.alice.id)
    assert created1 and not created2
    assert chat1.id == chat2.id


@pytest.mark.asyncio
async def test_group_create_owner_and_members(db: AsyncSession, actors: Actors) -> None:
    async with await ac() as c:
        r = await c.post(
            "/api/v1/chats",
            json={"title": "Team", "member_ids": [actors.bob.id, actors.carol.id]},
        )
        assert r.status_code == 201, r.text
        chat_id = r.json()["id"]

        # creator в member_ids игнорируется, но добавляется как owner
        r2 = await c.post(
            "/api/v1/chats",
            json={"title": "T2", "member_ids": [actors.alice.id, actors.bob.id]},
        )
        assert r2.status_code == 201

        r3 = await c.get(f"/api/v1/chats/{chat_id}")
        assert r3.status_code == 200
        roles = {m["user_id"]: m["role"] for m in r3.json()["members"]}
        assert roles[actors.alice.id] == "owner"
        assert roles[actors.bob.id] == "member"


@pytest.mark.asyncio
async def test_group_requires_member_ids(db: AsyncSession, actors: Actors) -> None:
    async with await ac() as c:
        r = await c.post("/api/v1/chats", json={"title": "Empty", "member_ids": []})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_add_members_idempotent(db: AsyncSession, actors: Actors) -> None:
    async with await ac() as c:
        r = await c.post("/api/v1/chats", json={"title": "T", "member_ids": [actors.bob.id]})
        chat_id = r.json()["id"]

        # carol новая, bob уже участник — идемпотентно
        r2 = await c.post(
            f"/api/v1/chats/{chat_id}/members",
            json={"title": "x", "member_ids": [actors.carol.id, actors.bob.id]},
        )
        assert r2.status_code == 204

        r3 = await c.get(f"/api/v1/chats/{chat_id}")
        member_ids = {m["user_id"] for m in r3.json()["members"]}
        assert member_ids == {actors.alice.id, actors.bob.id, actors.carol.id}


@pytest.mark.asyncio
async def test_member_cannot_add_members(db: AsyncSession, actors: Actors) -> None:
    async with await ac() as c:
        r = await c.post("/api/v1/chats", json={"title": "T", "member_ids": [actors.bob.id]})
        chat_id = r.json()["id"]

        actors.act_as("bob")  # bob — обычный member
        r2 = await c.post(
            f"/api/v1/chats/{chat_id}/members",
            json={"title": "x", "member_ids": [actors.carol.id]},
        )
        assert r2.status_code == 403


@pytest.mark.asyncio
async def test_owner_transfer_and_leave(db: AsyncSession, actors: Actors) -> None:
    async with await ac() as c:
        r = await c.post("/api/v1/chats", json={"title": "T", "member_ids": [actors.bob.id]})
        chat_id = r.json()["id"]

        # owner'а исключить нельзя
        r2 = await c.delete(f"/api/v1/chats/{chat_id}/members/{actors.alice.id}")
        assert r2.status_code == 403

        # передача владения bob'у
        r3 = await c.post(f"/api/v1/chats/{chat_id}/owner", json={"user_id": actors.bob.id})
        assert r3.status_code == 204

        # теперь alice (admin) может выйти
        r4 = await c.delete(f"/api/v1/chats/{chat_id}/members/{actors.alice.id}")
        assert r4.status_code == 204

        actors.act_as("bob")
        r5 = await c.get(f"/api/v1/chats/{chat_id}")
        roles = {m["user_id"]: m["role"] for m in r5.json()["members"]}
        assert roles[actors.bob.id] == "owner"
        assert actors.alice.id not in roles


@pytest.mark.asyncio
async def test_non_member_forbidden(db: AsyncSession, actors: Actors) -> None:
    async with await ac() as c:
        r = await c.post("/api/v1/chats", json={"title": "T", "member_ids": [actors.bob.id]})
        chat_id = r.json()["id"]

        actors.act_as("carol")  # не участник
        r2 = await c.get(f"/api/v1/chats/{chat_id}")
        assert r2.status_code == 403


@pytest.mark.asyncio
async def test_delete_chat_soft(db: AsyncSession, actors: Actors) -> None:
    async with await ac() as c:
        r = await c.post("/api/v1/chats", json={"title": "T", "member_ids": [actors.bob.id]})
        chat_id = r.json()["id"]

        actors.act_as("bob")
        r2 = await c.delete(f"/api/v1/chats/{chat_id}")
        assert r2.status_code == 403

        actors.act_as("alice")
        r3 = await c.delete(f"/api/v1/chats/{chat_id}")
        assert r3.status_code == 204

        r4 = await c.get("/api/v1/chats")
        assert chat_id not in [ch["id"] for ch in r4.json()]

        r5 = await c.get(f"/api/v1/chats/{chat_id}")
        assert r5.status_code == 404


@pytest.mark.asyncio
async def test_user_search_finds_bot(db: AsyncSession, actors: Actors) -> None:
    """GET /users?q= находит людей и ботов (is_bot в ответе, §12)."""
    bot = await upsert_user_by_sub(db, sub="", preferred_username="deploy-bot")
    bot.is_bot = True
    await db.commit()

    async with await ac() as c:
        r = await c.get("/api/v1/users?q=bot")
        assert r.status_code == 200
        found = r.json()
        assert any(u["username"] == "deploy-bot" and u["is_bot"] for u in found)
