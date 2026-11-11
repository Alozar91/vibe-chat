"""Тесты профиля: PATCH /users/me (§5 — персональные данные только в системе)."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any

import pytest
from app.api.deps import current_user
from app.core import valkey as valkey_core
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.services.users import upsert_user_by_sub
from fastapi import Depends
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
        target_id: str = getattr(self, name).id

        async def _override(
            db: Annotated[AsyncSession, Depends(get_db)],
        ) -> User:
            # как в проде: current_user работает в сессии запроса (Depends(get_db)
            # кэшируется — это та же сессия, что у роута), инстанс всегда свежий
            user = await db.get(User, target_id)
            assert user is not None
            return user

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


# --- PATCH /users/me: базовое обновление (§5, §12) ---


@pytest.mark.asyncio
async def test_patch_me_updates_personal_fields(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.patch(
            "/api/v1/users/me",
            json={
                "display_name": "Алиса Селезнёва",
                "first_name": "Алиса",
                "last_name": "Селезнёва",
                "email": "alisa@example.com",
                "timezone": "Europe/Moscow",
                "time_display": "fixed",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["display_name"] == "Алиса Селезнёва"
        assert body["first_name"] == "Алиса"
        assert body["last_name"] == "Селезнёва"
        assert body["email"] == "alisa@example.com"
        assert body["timezone"] == "Europe/Moscow"
        assert body["time_display"] == "fixed"

    # данные реально в БД системы, а не в токене; expire_all — сбросить кэш
    # identity map (сессия теста видит старые значения), select — перечитать
    from sqlalchemy import select

    db.expire_all()
    fresh = (await db.execute(select(User).where(User.keycloak_sub == "sub-a"))).scalar_one()
    assert fresh.first_name == "Алиса"
    assert fresh.email == "alisa@example.com"


@pytest.mark.asyncio
async def test_patch_me_partial_missing_fields_untouched(db: AsyncSession, actors: Actors) -> None:
    """Частичное обновление: не переданные поля не сбрасываются."""
    actors.act_as("alice")
    async with await ac() as c:
        await c.patch("/api/v1/users/me", json={"first_name": "Алиса", "email": "a@e.com"})
        r = await c.patch("/api/v1/users/me", json={"last_name": "Селезнёва"})
        assert r.status_code == 200
        assert r.json()["first_name"] == "Алиса"  # не затёрт
        assert r.json()["email"] == "a@e.com"
        assert r.json()["last_name"] == "Селезнёва"


@pytest.mark.asyncio
async def test_patch_me_null_clears_field(db: AsyncSession, actors: Actors) -> None:
    """Явный null — очистить поле."""
    actors.act_as("alice")
    async with await ac() as c:
        await c.patch("/api/v1/users/me", json={"first_name": "Алиса"})
        r = await c.patch("/api/v1/users/me", json={"first_name": None})
        assert r.status_code == 200
        assert r.json()["first_name"] is None


# --- Валидация ---


@pytest.mark.asyncio
async def test_patch_me_invalid_timezone_422(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.patch("/api/v1/users/me", json={"timezone": "Mars/Olympus"})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_me_invalid_time_display_422(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.patch("/api/v1/users/me", json={"time_display": "always"})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_me_unknown_field_422(db: AsyncSession, actors: Actors) -> None:
    """extra=forbid: неизвестные поля (например попытка подменить username/is_bot) — 422."""
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.patch("/api/v1/users/me", json={"is_bot": True})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_me_empty_display_name_422(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("alice")
    async with await ac() as c:
        r = await c.patch("/api/v1/users/me", json={"display_name": ""})
        assert r.status_code == 422


# --- Isolation: Keycloak-клеймы не влияют (§5) ---


@pytest.mark.asyncio
async def test_jwt_claims_do_not_overwrite_profile(db: AsyncSession, actors: Actors) -> None:
    """Повторный upsert (каждый запрос) не сбрасывает персональные данные — они в системе."""
    actors.act_as("alice")
    async with await ac() as c:
        await c.patch("/api/v1/users/me", json={"display_name": "Алиса", "email": "alisa@example.com"})

    # эмулируем повторный вход: upsert по тому же sub с другим preferred_username
    # (expire_all — сбросить stale identity map тестовой сессии)
    db.expire_all()
    user = await upsert_user_by_sub(db, sub="sub-a", preferred_username="someone-else")
    assert user.username == "alice"  # username не меняется
    assert user.display_name == "Алиса"
    assert user.email == "alisa@example.com"


# --- GET /users/me отдаёт персональные поля ---


@pytest.mark.asyncio
async def test_get_me_includes_personal_fields(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("alice")
    async with await ac() as c:
        await c.patch("/api/v1/users/me", json={"first_name": "Алиса"})
        r = await c.get("/api/v1/users/me")
        assert r.status_code == 200
        body: dict[str, Any] = json.loads(r.text)
        assert body["first_name"] == "Алиса"
        assert body["last_name"] is None
        assert body["email"] is None
        assert body["username"] == "alice"
    _ = db  # сессия нужна фикстуре actors; проверки — через HTTP-ответ

