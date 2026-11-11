"""Тесты ботов (§10): управление платформенным админом, токены vbt_, Bot API, long polling.

Valkey подменяется фейком с поддержкой Streams (xadd/xrange/xread/xtrim).
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
from app.models.bot import BotProfile
from app.models.user import User
from app.services import bots as bot_service
from app.services.chats import create_group
from app.services.users import upsert_user_by_sub
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# --- Fake Valkey: KV + Pub/Sub + Streams ---


def _sid_parts(entry_id: str) -> tuple[int, int]:
    ms, _, seq = entry_id.partition("-")
    return int(ms), int(seq or 0)


class FakeValkey:
    """KV (tickets/presence) + publish + Streams для ботов (§10)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._sid_counter = 1000

    # --- KV ---
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

    # --- Pub/Sub ---
    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1

    # --- Streams (§10) ---
    async def xadd(
        self,
        key: str,
        fields: dict[str, str],
        id: str = "*",
        maxlen: int | None = None,
        approximate: bool | None = None,
    ) -> str:
        self._sid_counter += 1
        entry_id = f"{self._sid_counter}-0"
        self.streams.setdefault(key, []).append((entry_id, dict(fields)))
        return entry_id

    async def xrange(
        self, key: str, min: str = "-", max: str = "+", count: int | None = None
    ) -> list[tuple[str, dict[str, str]]]:
        entries = self.streams.get(key, [])
        if min not in ("-", ""):
            entries = [e for e in entries if _sid_parts(e[0]) >= _sid_parts(min)]
        if max not in ("+", ""):
            entries = [e for e in entries if _sid_parts(e[0]) <= _sid_parts(max)]
        return entries[:count] if count else entries

    async def xread(
        self,
        streams: dict[str, str],
        block: int | None = None,
        count: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        """Неблокирующая эмуляция: есть новые — возвращает сразу, нет — пусто."""
        result = []
        for key, last_id in streams.items():
            entries = [e for e in self.streams.get(key, []) if _sid_parts(e[0]) > _sid_parts(last_id)]
            if entries:
                result.append((key, entries[:count] if count else entries))
        return result

    async def xtrim(
        self, key: str, minid: str | None = None, maxlen: int | None = None, approximate: bool | None = None
    ) -> int:
        """Эмуляция retention-чистки: удаляет entries со временем ms < minid."""
        if minid is None:
            return 0
        min_ms = _sid_parts(minid)[0]
        entries = self.streams.get(key, [])
        kept = [e for e in entries if _sid_parts(e[0])[0] >= min_ms]
        removed = len(entries) - len(kept)
        self.streams[key] = kept
        return removed

    async def aclose(self) -> None:
        pass


@pytest.fixture
def fake_valkey(monkeypatch: pytest.MonkeyPatch) -> FakeValkey:
    fake = FakeValkey()
    monkeypatch.setattr(valkey_core, "get_valkey", lambda: fake)
    monkeypatch.setattr(valkey_core, "_client", None)
    return fake


# --- DB + actors ---


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
    """admin (платформенный админ), alice (обычный), bot-создание — через сервис."""

    admin: User
    alice: User

    def act_as(self, name: str) -> None:
        target: User = getattr(self, name)

        def _override() -> User:
            return target

        app.dependency_overrides[current_user] = _override


@pytest.fixture
async def actors(db: AsyncSession) -> Actors:
    admin = await upsert_user_by_sub(db, sub="sub-admin", preferred_username="admin")
    admin.is_platform_admin = True
    alice = await upsert_user_by_sub(db, sub="sub-a", preferred_username="alice")
    await db.commit()
    a = Actors(admin=admin, alice=alice)
    a.act_as("admin")
    return a


async def ac() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def create_bot_via_api(db: AsyncSession, actors: Actors, username: str = "helper") -> tuple[User, str]:
    """Создаёт бота через API; возвращает (bot_user, токен)."""
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post(
            "/api/v1/bots",
            json={"username": username, "display_name": "Helper Bot"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
    bot_user = await db.get(User, body["id"])
    assert bot_user is not None
    return bot_user, body["token"]


# --- Управление: только платформенный админ (§10) ---


@pytest.mark.asyncio
async def test_create_bot_requires_platform_admin(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post("/api/v1/bots", json={"username": "bot1", "display_name": "B1"})
        assert r.status_code == 403, r.text
        # чтение списка тоже только для админа
        r2 = await c.get("/api/v1/bots")
        assert r2.status_code == 403


@pytest.mark.asyncio
async def test_create_bot_by_admin_token_once(db: AsyncSession, actors: Actors) -> None:
    bot_user, token = await create_bot_via_api(db, actors)

    # users.is_bot=True, keycloak_sub NULL (§6)
    assert bot_user.is_bot is True
    assert bot_user.keycloak_sub is None

    # токен vbt_..., хранится только sha256 (§10)
    assert token.startswith("vbt_")
    profile = await db.get(BotProfile, bot_user.id)
    assert profile is not None
    assert profile.token_hash == bot_service.hash_bot_token(token)
    assert profile.token_hash != token


@pytest.mark.asyncio
async def test_bot_username_collision_suffix(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("admin")
    async with await ac() as c:
        r1 = await c.post("/api/v1/bots", json={"username": "dup", "display_name": "D1"})
        r2 = await c.post("/api/v1/bots", json={"username": "dup", "display_name": "D2"})
        assert r1.status_code == 201 and r2.status_code == 201
        assert r1.json()["username"] == "dup"
        assert r2.json()["username"] == "dup-1"


# --- authenticate_bot: валид / невалид / деактив / регенерация (§10) ---


@pytest.mark.asyncio
async def test_authenticate_bot_valid_and_invalid(db: AsyncSession, actors: Actors) -> None:
    bot_user, token = await create_bot_via_api(db, actors)

    user, profile = await bot_service.authenticate_bot(db, f"Bearer {token}")
    assert user.id == bot_user.id
    assert profile.user_id == bot_user.id

    with pytest.raises(HTTPException) as exc:
        await bot_service.authenticate_bot(db, "Bearer vbt_wrong-token")
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc2:
        await bot_service.authenticate_bot(db, None)
    assert exc2.value.status_code == 401


@pytest.mark.asyncio
async def test_deactivated_bot_rejected(db: AsyncSession, actors: Actors) -> None:
    bot_user, token = await create_bot_via_api(db, actors)
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.patch(f"/api/v1/bots/{bot_user.id}", json={"is_active": False})
        assert r.status_code == 200, r.text
        assert r.json()["is_active"] is False

    db.expire_all()  # бот ходит со своей сессией — берём свежие данные из БД
    with pytest.raises(HTTPException) as exc:
        await bot_service.authenticate_bot(db, f"Bearer {token}")
    assert exc.value.status_code == 401
    assert "deactivated" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_regenerate_token_invalidates_old(db: AsyncSession, actors: Actors) -> None:
    bot_user, old_token = await create_bot_via_api(db, actors)
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post(f"/api/v1/bots/{bot_user.id}/token/regenerate")
        assert r.status_code == 200, r.text
        new_token = r.json()["token"]
    assert new_token != old_token

    with pytest.raises(HTTPException):
        await bot_service.authenticate_bot(db, f"Bearer {old_token}")
    user, _profile = await bot_service.authenticate_bot(db, f"Bearer {new_token}")
    assert user.id == bot_user.id


# --- Bot API: membership, история, отправка с идемпотентностью (§10) ---


@pytest.mark.asyncio
async def test_bot_api_requires_member(db: AsyncSession, actors: Actors) -> None:
    bot_user, token = await create_bot_via_api(db, actors)
    chat = await create_group(
        db, creator_id=actors.alice.id, title="T", member_ids=[actors.alice.id]
    )

    async with await ac() as c:
        r = await c.get(
            f"/api/v1/bot/chats/{chat.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403, r.text  # бот не участник чата

        # bot/me и /bot/chats работают без membership
        r_me = await c.get("/api/v1/bot/me", headers={"Authorization": f"Bearer {token}"})
        assert r_me.status_code == 200
        assert r_me.json()["id"] == bot_user.id


@pytest.mark.asyncio
async def test_bot_send_message_idempotent(db: AsyncSession, actors: Actors) -> None:
    bot_user, token = await create_bot_via_api(db, actors)
    chat = await create_group(
        db, creator_id=actors.alice.id, title="T", member_ids=[actors.alice.id, bot_user.id]
    )

    headers = {"Authorization": f"Bearer {token}"}
    payload = {"chat_id": chat.id, "text": "бот отвечает", "client_ref": "ref-1"}
    async with await ac() as c:
        r1 = await c.post("/api/v1/bot/messages", json=payload, headers=headers)
        assert r1.status_code == 201, r1.text
        r2 = await c.post("/api/v1/bot/messages", json=payload, headers=headers)
        assert r2.status_code == 201
        # идемпотентность: тот же message (§10)
        assert r1.json()["id"] == r2.json()["id"]
        # у ботов timezone NULL (§6)
        assert r1.json()["timezone"] is None


@pytest.mark.asyncio
async def test_bot_reads_history(db: AsyncSession, actors: Actors) -> None:
    bot_user, token = await create_bot_via_api(db, actors)
    chat = await create_group(
        db, creator_id=actors.alice.id, title="T", member_ids=[actors.alice.id, bot_user.id]
    )
    from app.services import messages as message_service

    await message_service.create_message(
        db, sender=actors.alice, chat_id=chat.id, text="вопрос", attachments=[],
        reply_to_id=None, timezone_name=None, client_ref=None,
    )

    async with await ac() as c:
        r = await c.get(
            f"/api/v1/bot/chats/{chat.id}/messages",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        texts = [m["text"] for m in r.json()]
        assert "вопрос" in texts


# --- Fanout: события боту-участнику чата (§10) ---


@pytest.mark.asyncio
async def test_fanout_message_new_to_bot_stream(
    db: AsyncSession, actors: Actors, fake_valkey: FakeValkey
) -> None:
    bot_user, _token = await create_bot_via_api(db, actors)
    chat = await create_group(
        db, creator_id=actors.alice.id, title="T", member_ids=[actors.alice.id, bot_user.id]
    )

    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post(f"/api/v1/chats/{chat.id}/messages", json={"text": "привет боту"})
        assert r.status_code == 201

    key = await bot_service.stream_key(bot_user.id)
    entries = fake_valkey.streams.get(key, [])
    events = [json.loads(fields["event"]) for _eid, fields in entries]
    assert any(e["type"] == "message.new" and e["data"]["text"] == "привет боту" for e in events)


@pytest.mark.asyncio
async def test_fanout_skips_chats_without_bots(
    db: AsyncSession, actors: Actors, fake_valkey: FakeValkey
) -> None:
    chat = await create_group(db, creator_id=actors.alice.id, title="T", member_ids=[actors.alice.id])
    actors.act_as("alice")
    async with await ac() as c:
        await c.post(f"/api/v1/chats/{chat.id}/messages", json={"text": "x"})
    assert fake_valkey.streams == {}  # ботов нет — стримы не создавались


# --- Long polling /bot/updates: offset, resync (§10) ---


@pytest.mark.asyncio
async def test_read_updates_from_start_and_by_offset(
    db: AsyncSession, actors: Actors, fake_valkey: FakeValkey
) -> None:
    bot_user, token = await create_bot_via_api(db, actors)
    key = await bot_service.stream_key(bot_user.id)
    await bot_service.push_bot_event(bot_user.id, "message.new", {"id": "m1"})
    await bot_service.push_bot_event(bot_user.id, "message.new", {"id": "m2"})

    async with await ac() as c:
        # с начала
        r1 = await c.get("/api/v1/bot/updates?timeout=0", headers={"Authorization": f"Bearer {token}"})
        assert r1.status_code == 200, r1.text
        body1 = r1.json()
        assert body1["resync"] is False
        assert [u["data"]["id"] for u in body1["updates"]] == ["m1", "m2"]
        assert body1["offset"] == body1["updates"][-1]["offset"]

        # с offset после первого события
        first_offset = body1["updates"][0]["offset"]
        r2 = await c.get(
            f"/api/v1/bot/updates?timeout=0&offset={first_offset}",
            headers={"Authorization": f"Bearer {token}"},
        )
        body2 = r2.json()
        assert [u["data"]["id"] for u in body2["updates"]] == ["m2"]
        assert body2["resync"] is False

        # догнали до конца: пусто, offset не откатывается
        r3 = await c.get(
            f"/api/v1/bot/updates?timeout=0&offset={body2['offset']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        body3 = r3.json()
        assert body3["updates"] == []
        assert body3["offset"] == body2["offset"]

        _ = key  # silence


@pytest.mark.asyncio
async def test_read_updates_resync_after_retention_eviction(
    db: AsyncSession, actors: Actors, fake_valkey: FakeValkey
) -> None:
    bot_user, token = await create_bot_via_api(db, actors)
    key = await bot_service.stream_key(bot_user.id)
    await bot_service.push_bot_event(bot_user.id, "message.new", {"id": "m1"})
    await bot_service.push_bot_event(bot_user.id, "message.new", {"id": "m2"})

    # читаем первое событие → offset первого entry
    async with await ac() as c:
        r1 = await c.get("/api/v1/bot/updates?timeout=0", headers={"Authorization": f"Bearer {token}"})
        body1 = r1.json()
        first_offset = body1["updates"][0]["offset"]

        # retention вытеснил оба события; в стриме осталось только «будущее»
        fake_valkey.streams[key] = [
            (e_id, f) for e_id, f in fake_valkey.streams[key] if _sid_parts(e_id)[0] >= 10_000
        ]
        fake_valkey.streams[key].append(("999999-0", {"event": json.dumps({"type": "message.new", "data": {"id": "m3"}})}))

        r2 = await c.get(
            f"/api/v1/bot/updates?timeout=0&offset={first_offset}",
            headers={"Authorization": f"Bearer {token}"},
        )
        body2 = r2.json()
        assert body2["resync"] is True, body2  # offset старше retention → resync (§10)
        assert body2["updates"] == []


@pytest.mark.asyncio
async def test_push_bot_event_never_raises_on_valkey_down(
    db: AsyncSession, actors: Actors, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Недоступный Valkey не роняет источник мутации (мягкая деградация)."""

    class BrokenValkey:
        def __getattr__(self, name: str) -> Any:  # noqa: ANN001
            raise ConnectionError("valkey down")

    monkeypatch.setattr(valkey_core, "get_valkey", lambda: BrokenValkey())

    await bot_service.push_bot_event("some-bot", "message.new", {"id": "m"})  # не падает
