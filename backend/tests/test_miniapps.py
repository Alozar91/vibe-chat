"""Тесты mini-apps каркаса (§11): handoff-коды, mat_-токены, mat-auth в обычном REST.

Valkey подменяется фейком (in-memory); JWT не участвует — current_user
override'ится, кроме тестов mat_-ветки require_auth (через dependency_overrides).
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from app.api.deps import current_user
from app.core import valkey as valkey_core
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.bot import BotProfile
from app.models.user import User
from app.services import miniapps
from app.services.chats import create_group
from app.services.users import upsert_user_by_sub
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class FakeValkey:
    """KV (коды, mat-токены) + publish; Streams не нужны здесь."""

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
def vk(monkeypatch: pytest.MonkeyPatch) -> FakeValkey:
    """Фейковый Valkey; аргумент `vk` в тестах (не путать с именем фикстуры)."""
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
    admin: User
    alice: User
    bob: User

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
    bob = await upsert_user_by_sub(db, sub="sub-b", preferred_username="bob")
    await db.commit()
    a = Actors(admin=admin, alice=alice, bob=bob)
    a.act_as("alice")
    return a


async def ac() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def create_bot(db: AsyncSession, actors: Actors) -> tuple[User, str]:
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post("/api/v1/bots", json={"username": "appbot", "display_name": "App Bot"})
        assert r.status_code == 201, r.text
        body = r.json()
    bot_user = await db.get(User, body["id"])
    assert bot_user is not None
    return bot_user, body["token"]


# --- HTTPS-валидация miniapp_url (§11) ---


@pytest.mark.asyncio
async def test_miniapp_url_must_be_https(db: AsyncSession, actors: Actors) -> None:
    bot_user, _token = await create_bot(db, actors)
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.patch(
            f"/api/v1/bots/{bot_user.id}",
            json={"miniapp_url": "http://app.example.com"},
        )
        assert r.status_code == 422, r.text

        ok = await c.patch(
            f"/api/v1/bots/{bot_user.id}",
            json={"miniapp_url": "https://app.example.com", "miniapp_name": "App"},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["miniapp_url"] == "https://app.example.com"


# --- POST /miniapps/{bot_id}/code (§11) ---


@pytest.mark.asyncio
async def test_code_requires_shared_chat(
    db: AsyncSession, actors: Actors, vk: FakeValkey
) -> None:
    bot_user, _token = await create_bot(db, actors)

    # alice не в чате с ботом → 403
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post(f"/api/v1/miniapps/{bot_user.id}/code")
        assert r.status_code == 403, r.text

    # bob добавил бота в чат → код выдаётся
    await create_group(
        db, creator_id=actors.bob.id, title="T", member_ids=[actors.bob.id, bot_user.id]
    )
    actors.act_as("bob")
    async with await ac() as c:
        r2 = await c.post(f"/api/v1/miniapps/{bot_user.id}/code")
        assert r2.status_code == 201, r2.text
        body = r2.json()
        assert body["code"].startswith("vac_")
        assert body["expires_in"] == 60

        # код лежит в Valkey с привязкой user+bot (§11)
        raw = vk.store.get(f"miniapp_code:{body['code']}")
        assert raw is not None
        stored = json.loads(raw)
        assert stored == {"user_id": actors.bob.id, "bot_id": bot_user.id}


@pytest.mark.asyncio
async def test_code_unknown_bot_404(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.post("/api/v1/miniapps/ghost-bot/code")
        assert r.status_code == 404


# --- POST /miniapps/token (§11) ---


async def _get_code(db: AsyncSession, actors: Actors, bot_user: User, as_: str) -> str:
    actors.act_as(as_)
    async with await ac() as c:
        r = await c.post(f"/api/v1/miniapps/{bot_user.id}/code")
        assert r.status_code == 201, r.text
        return str(r.json()["code"])


@pytest.mark.asyncio
async def test_token_exchange_full_handoff(
    db: AsyncSession, actors: Actors, vk: FakeValkey
) -> None:
    bot_user, _bot_token = await create_bot(db, actors)
    await create_group(
        db, creator_id=actors.bob.id, title="T", member_ids=[actors.bob.id, bot_user.id]
    )
    code = await _get_code(db, actors, bot_user, "bob")

    async with await ac() as c:
        r = await c.post("/api/v1/miniapps/token", json={"code": code})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["token"].startswith("mat_")
        assert body["expires_in"] == 900
        assert body["user_id"] == actors.bob.id
        assert body["bot_id"] == bot_user.id

        # в Valkey — только sha256-хэш токена (§11)
        token_hash = miniapps.token_hash(body["token"])
        assert f"miniapp_token:{token_hash}" in vk.store
        assert body["token"] not in json.dumps(vk.store)

        # повторный обмен тем же кодом — 401 (одноразовость GETDEL, §11)
        r2 = await c.post("/api/v1/miniapps/token", json={"code": code})
        assert r2.status_code == 401


@pytest.mark.asyncio
async def test_token_exchange_invalid_code(db: AsyncSession, actors: Actors) -> None:
    async with await ac() as c:
        r = await c.post("/api/v1/miniapps/token", json={"code": "vac_nonexistent"})
        assert r.status_code == 401


# --- mat_-токен работает в обычном REST (§11: «далее обычный REST») ---


@pytest.mark.asyncio
async def test_mat_token_works_on_rest(db: AsyncSession, actors: Actors) -> None:
    bot_user, _bt = await create_bot(db, actors)
    await create_group(
        db, creator_id=actors.bob.id, title="T", member_ids=[actors.bob.id, bot_user.id]
    )
    code = await _get_code(db, actors, bot_user, "bob")
    async with await ac() as c:
        tok = (await c.post("/api/v1/miniapps/token", json={"code": code})).json()

    # НЕ override'им current_user: идём настоящим mat_-путём через require_auth
    app.dependency_overrides.pop(current_user, None)
    async with await ac() as c:
        r = await c.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {tok['token']}"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["id"] == actors.bob.id


@pytest.mark.asyncio
async def test_mat_token_expired_or_unknown_401(db: AsyncSession, actors: Actors) -> None:
    app.dependency_overrides.pop(current_user, None)
    async with await ac() as c:
        r = await c.get(
            "/api/v1/users/me", headers={"Authorization": "Bearer mat_unknown-token"}
        )
        assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_jwt_still_works_alongside_mat(db: AsyncSession, actors: Actors) -> None:
    """Регресс: обычный JWT-путь не сломан (mat-ветка в require_auth не мешает)."""
    app.dependency_overrides.pop(current_user, None)
    # без токена — 401 (JWT-ветка), JWKS не трогаем
    async with await ac() as c:
        r = await c.get("/api/v1/users/me")
        assert r.status_code == 401


# --- Юнит: resolve/consume (§11) ---


@pytest.mark.asyncio
async def test_consume_code_one_time_unit(db: AsyncSession, actors: Actors) -> None:
    session = await miniapps.create_code(user_id="u1", bot_id="b1")
    code = session  # create_code возвращает строку кода
    first = await miniapps.consume_code(code)
    assert first == {"user_id": "u1", "bot_id": "b1"}
    assert await miniapps.consume_code(code) is None


@pytest.mark.asyncio
async def test_resolve_mat_token(db: AsyncSession, actors: Actors) -> None:
    token = miniapps.generate_mat_token()
    assert await miniapps.resolve_mat_token(token) is None  # не сохранён
    await miniapps.store_mat_token(token=token, user_id="u1", bot_id="b1")
    resolved = await miniapps.resolve_mat_token(token)
    assert resolved == {"user_id": "u1", "bot_id": "b1"}


_ = BotProfile  # реестр моделей; используется Alembic-метаданными
