"""Тесты звонков (§17): lifecycle direct/group, права, токены, cleanup, system-сообщения.

LiveKit не конфигурирован в тестовом окружении → /calls/token даёт 503;
room-токен тестируется напрямую issue_room_token с подменой настроек.
Auth подменяется dependency_overrides (как в test_chats.py).
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from app.api.deps import current_user
from app.core import valkey as valkey_core
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.services import calls as call_service
from app.services.calls_tokens import issue_room_token
from app.services.users import upsert_user_by_sub
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class FakeValkey:
    """KV + publish (достаточно для call.* событий)."""

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
def fake_valkey(monkeypatch: pytest.MonkeyPatch) -> FakeValkey:
    fake = FakeValkey()
    monkeypatch.setattr(valkey_core, "get_valkey", lambda: fake)
    monkeypatch.setattr(valkey_core, "_client", None)
    return fake


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
    alice: User
    bob: User
    carol: User

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
        carol=await upsert_user_by_sub(db, sub="sub-c", preferred_username="carol"),
    )
    a.act_as("alice")
    return a


async def ac() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def make_direct(actors: Actors) -> str:
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post("/api/v1/chats/direct", json={"user_id": actors.bob.id})
        assert r.status_code == 201, r.text
        return r.json()["chat_id"]


async def make_group(actors: Actors) -> str:
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post("/api/v1/chats", json={"title": "T", "member_ids": [actors.bob.id, actors.carol.id]})
        assert r.status_code == 201, r.text
        return r.json()["id"]


# --- Direct: ringing-модель ---


@pytest.mark.asyncio
async def test_direct_call_happy_path(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_direct(actors)

    # alice звонит
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post("/api/v1/calls", json={"chat_id": chat_id, "kind": "audio"})
        assert r.status_code == 201, r.text
        call = r.json()
        assert call["status"] == "ringing"
        assert call["kind"] == "audio"
        assert call["initiator_id"] == actors.alice.id
        assert actors.alice.id in call["participant_ids"]
        call_id = call["id"]

        # повторный старт тем же инициатором — тот же звонок (без нового ринга)
        r2 = await c.post("/api/v1/calls", json={"chat_id": chat_id, "kind": "audio"})
        assert r2.status_code == 201
        assert r2.json()["id"] == call_id

        # bob отвечает
        actors.act_as("bob")
        r3 = await c.post(f"/api/v1/calls/{call_id}/accept")
        assert r3.status_code == 200, r3.text
        assert r3.json()["status"] == "active"
        assert r3.json()["started_at"] is not None

        # bob сбрасывает — direct 1:1: звонок завершается для обоих (§17)
        r4 = await c.post(f"/api/v1/calls/{call_id}/leave")
        assert r4.status_code == 200
        assert r4.json()["status"] == "ended"
        assert r4.json()["ended_at"] is not None

    # system-сообщение о звонке в ленте
    actors.act_as("alice")
    async with await ac() as c:
        r5 = await c.get(f"/api/v1/chats/{chat_id}/messages")
        kinds = [m["payload"].get("kind") for m in r5.json() if m["type"] == "system"]
        assert "call_ended" in kinds


@pytest.mark.asyncio
async def test_direct_call_reject_and_cancel(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_direct(actors)

    # reject получателем
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post("/api/v1/calls", json={"chat_id": chat_id, "kind": "audio"})
        call_id = r.json()["id"]

        actors.act_as("bob")
        r2 = await c.post(f"/api/v1/calls/{call_id}/reject")
        assert r2.status_code == 200
        assert r2.json()["status"] == "ended"

        # повторный accept/reject — 409 (уже ended)
        r3 = await c.post(f"/api/v1/calls/{call_id}/accept")
        assert r3.status_code == 409

    # cancel инициатором (новый звонок)
    actors.act_as("alice")
    async with await ac() as c:
        r4 = await c.post("/api/v1/calls", json={"chat_id": chat_id, "kind": "audio"})
        call_id2 = r4.json()["id"]

        # cancel не-инициатором — 403
        actors.act_as("bob")
        r5 = await c.post(f"/api/v1/calls/{call_id2}/cancel")
        assert r5.status_code == 403

        actors.act_as("alice")
        r6 = await c.post(f"/api/v1/calls/{call_id2}/cancel")
        assert r6.status_code == 200
        assert r6.json()["status"] == "ended"

    # оба system-сообщения: rejected (missed) + cancelled
    async with await ac() as c:
        r7 = await c.get(f"/api/v1/chats/{chat_id}/messages")
        kinds = [m["payload"].get("kind") for m in r7.json() if m["type"] == "system"]
        assert kinds.count("call_missed") >= 1


@pytest.mark.asyncio
async def test_call_while_another_ringing_409(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_direct(actors)

    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post("/api/v1/calls", json={"chat_id": chat_id, "kind": "audio"})
        assert r.status_code == 201

        # bob не может начать свой звонок, пока висит ringing alice
        actors.act_as("bob")
        r2 = await c.post("/api/v1/calls", json={"chat_id": chat_id, "kind": "audio"})
        assert r2.status_code == 409


@pytest.mark.asyncio
async def test_non_member_cannot_call(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_direct(actors)  # alice + bob, carol не участник

    actors.act_as("carol")
    async with await ac() as c:
        r = await c.post("/api/v1/calls", json={"chat_id": chat_id, "kind": "audio"})
        assert r.status_code == 403


# --- Group: join-модель ---


@pytest.mark.asyncio
async def test_group_call_join_leave(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_group(actors)

    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post("/api/v1/calls", json={"chat_id": chat_id, "kind": "audio"})
        assert r.status_code == 201, r.text
        call_id = r.json()["id"]
        assert r.json()["status"] == "ringing"

        # bob и carol присоединяются без ринга каждому
        actors.act_as("bob")
        r2 = await c.post(f"/api/v1/calls/{call_id}/join")
        assert r2.status_code == 200
        assert r2.json()["status"] == "active"

        actors.act_as("carol")
        r3 = await c.post(f"/api/v1/calls/{call_id}/join")
        assert r3.status_code == 200
        assert set(r3.json()["participant_ids"]) == {actors.alice.id, actors.bob.id, actors.carol.id}

        # alice и bob выходят — carol осталась, звонок жив
        actors.act_as("alice")
        r4 = await c.post(f"/api/v1/calls/{call_id}/leave")
        assert r4.status_code == 200
        assert r4.json()["status"] == "active"

        actors.act_as("bob")
        r5 = await c.post(f"/api/v1/calls/{call_id}/leave")
        assert r5.status_code == 200
        assert r5.json()["status"] == "active"

        # carol вышла — ended
        actors.act_as("carol")
        r6 = await c.post(f"/api/v1/calls/{call_id}/leave")
        assert r6.status_code == 200
        assert r6.json()["status"] == "ended"


# --- Cleanup ---


@pytest.mark.asyncio
async def test_cleanup_stale_ringing(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_direct(actors)

    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post("/api/v1/calls", json={"chat_id": chat_id, "kind": "audio"})
        call_id = r.json()["id"]

    # звонок «создан 2 минуты назад»
    from datetime import UTC, datetime, timedelta

    call = await db.get(call_service.Call, call_id)
    assert call is not None
    call.created_at = datetime.now(UTC) - timedelta(minutes=2)
    await db.commit()

    closed = await call_service.cleanup_stale_calls(db)
    assert closed == 1
    refreshed = await db.get(call_service.Call, call_id)
    assert refreshed is not None
    assert refreshed.status == "ended"

    # в ленте — пропущенный
    actors.act_as("alice")
    async with await ac() as c:
        r2 = await c.get(f"/api/v1/chats/{chat_id}/messages")
        kinds = [m["payload"].get("kind") for m in r2.json() if m["type"] == "system"]
        assert "call_missed" in kinds


# --- Токены ---


@pytest.mark.asyncio
async def test_room_token_requires_config(db: AsyncSession, actors: Actors, monkeypatch: pytest.MonkeyPatch) -> None:
    chat_id = await make_direct(actors)

    # пустые ключи — звонки выключены (503); .env на стенде может их задавать
    settings = get_settings()
    monkeypatch.setattr(settings, "livekit_api_key", "")
    monkeypatch.setattr(settings, "livekit_api_secret", "")

    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post("/api/v1/calls", json={"chat_id": chat_id, "kind": "audio"})
        call_id = r.json()["id"]

        # не сконфигурирован → 503
        r2 = await c.post(f"/api/v1/calls/{call_id}/token")
        assert r2.status_code == 503


@pytest.mark.asyncio
async def test_room_token_shape(db: AsyncSession, actors: Actors, monkeypatch: pytest.MonkeyPatch) -> None:
    await make_direct(actors)

    settings = get_settings()
    monkeypatch.setattr(settings, "livekit_api_key", "devkey")
    monkeypatch.setattr(settings, "livekit_api_secret", "devsecret")

    token = issue_room_token(user_id="user-1", room="room-1")
    import jwt

    claims = jwt.decode(token, "devsecret", algorithms=["HS256"], options={"verify_aud": False})
    assert claims["iss"] == "devkey"
    assert claims["sub"] == "user-1"
    assert claims["video"]["room"] == "room-1"
    assert claims["video"]["roomJoin"] is True
