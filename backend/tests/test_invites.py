"""Тесты инвайт-регистрации (§5): multi-use коды, права, цикл регистрации, гонки, компенсация."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import pytest
from app.api.deps import current_user
from app.core import valkey as valkey_core
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.invite import Invite
from app.models.user import User
from app.services.users import upsert_user_by_sub
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class FakeValkey:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> Any:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return "OK"

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


class FakeKCAdmin:
    """Мок Keycloak Admin API: создаёт/удаляет «KC-аккаунты» в памяти."""

    def __init__(self) -> None:
        self.created: list[dict[str, str]] = []
        self.deleted: list[str] = []
        self.fail_create_with: int | None = None
        self.existing_usernames: set[str] = set()
        self.on_create: Any = None  # хук: эмуляция гонки в момент create_user

    async def create_user(self, *, username: str, password: str) -> str:
        if self.fail_create_with is not None:
            from fastapi import HTTPException, status

            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "kc down")
        if username in self.existing_usernames:
            from fastapi import HTTPException, status

            raise HTTPException(status.HTTP_409_CONFLICT, "username already taken")
        self.existing_usernames.add(username)
        kc_id = f"kc-{len(self.created) + 1}"
        self.created.append({"id": kc_id, "username": username, "password": password})
        if self.on_create is not None:
            await self.on_create()
        return kc_id

    async def delete_user(self, kc_user_id: str) -> None:
        self.deleted.append(kc_user_id)
        self.created = [c for c in self.created if c["id"] != kc_user_id]


@pytest.fixture
def vk(monkeypatch: pytest.MonkeyPatch) -> FakeValkey:
    fake = FakeValkey()
    monkeypatch.setattr(valkey_core, "get_valkey", lambda: fake)
    monkeypatch.setattr(valkey_core, "_client", None)
    return fake


@pytest.fixture
def kc(monkeypatch: pytest.MonkeyPatch) -> FakeKCAdmin:
    """Подменяет KC Admin клиент в роуте регистрации (без реального Keycloak)."""
    fake = FakeKCAdmin()
    import app.api.v1.invites as invites_router

    monkeypatch.setattr(invites_router, "get_kc_admin", lambda: fake)
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
    admin: User
    kc: "FakeKCAdmin"  # присваивается фикстурой actors

    def act_as(self, name: str) -> None:
        target_id: str = getattr(self, name).id

        async def _override(db: Annotated[AsyncSession, Depends(get_db)]) -> User:
            user = await db.get(User, target_id)
            assert user is not None
            return user

        app.dependency_overrides[current_user] = _override


@pytest.fixture
async def actors(db: AsyncSession, kc: FakeKCAdmin) -> AsyncIterator[Actors]:
    admin = await upsert_user_by_sub(db, sub="sub-admin", preferred_username="admin")
    admin.is_platform_admin = True
    alice = await upsert_user_by_sub(db, sub="sub-a", preferred_username="alice")
    db.add(admin)
    await db.commit()
    # FakeKCAdmin живёт в actors для удобных ассертов
    a = Actors(alice=alice, admin=admin, kc=kc)
    a.act_as("admin")
    yield a


async def ac() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --- Управление кодами (платформенный админ) ---


@pytest.mark.asyncio
async def test_create_invite_admin_only(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("alice")  # не админ
    async with await ac() as c:
        r = await c.post("/api/v1/invites", json={"max_uses": 5})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_invite_returns_code_once(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post("/api/v1/invites", json={"max_uses": 3})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["code"].startswith("vh_")
        assert body["max_uses"] == 3
        assert body["uses_count"] == 0

        # в БД только хэш, кода нет
        from app.services.invites import hash_invite_code

        inv = (await db.execute(select(Invite).where(Invite.id == body["id"]))).scalar_one()
        assert inv.code_hash == hash_invite_code(body["code"])


@pytest.mark.asyncio
async def test_invite_unlimited_when_no_max_uses(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post("/api/v1/invites", json={})
        assert r.status_code == 201
        assert r.json()["max_uses"] is None


# --- Регистрация: полный цикл ---


async def _register(c: AsyncClient, code: str, username: str, **extra: Any) -> Any:
    payload: dict[str, Any] = {
        "invite_code": code,
        "username": username,
        "password": "s3cret-pass",
        "first_name": "Иван",
        "last_name": "Иванов",
        "email": "ivan@example.com",
    }
    payload.update(extra)
    return await c.post("/api/v1/auth/register", json=payload)


@pytest.mark.asyncio
async def test_register_full_cycle(db: AsyncSession, actors: Actors) -> None:
    """Регистрация: KC-аккаунт (только credentials) + персональные данные в системе."""
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post("/api/v1/invites", json={"max_uses": None})
        code = r.json()["code"]

    actors_kc = actors.kc
    async with await ac() as c:
        r = await _register(c, code, "ivan")
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["username"] == "ivan"
        assert body["first_name"] == "Иван"
        assert body["email"] == "ivan@example.com"

    # KC получил только username+password, без персональных данных (§5)
    assert len(actors_kc.created) == 1
    kc_payload = actors_kc.created[0]
    assert kc_payload["username"] == "ivan"
    assert set(kc_payload) == {"id", "username", "password"}  # никаких name/email

    # пользователь в БД системы с персональными данными
    user = (await db.execute(select(User).where(User.username == "ivan"))).scalar_one()
    assert user.first_name == "Иван"
    assert user.last_name == "Иванов"
    assert user.email == "ivan@example.com"
    assert user.keycloak_sub is None  # заполнится при первом логине (JIT upsert)


@pytest.mark.asyncio
async def test_register_multi_use_code(db: AsyncSession, actors: Actors) -> None:
    """Multi-use: один код на несколько регистраций, лимит соблюдается."""
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post("/api/v1/invites", json={"max_uses": 2})
        code = r.json()["code"]

        assert (await _register(c, code, "user1")).status_code == 201
        assert (await _register(c, code, "user2")).status_code == 201

        # код исчерпан → 410, пользователь не создан
        r3 = await _register(c, code, "user3")
        assert r3.status_code == 410

    users = (await db.execute(select(User.username).where(User.username.like("user%")))).scalars().all()
    assert sorted(users) == ["user1", "user2"]


@pytest.mark.asyncio
async def test_register_deactivated_invite_410(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post("/api/v1/invites", json={})
        invite_id, code = r.json()["id"], r.json()["code"]
        d = await c.post(f"/api/v1/invites/{invite_id}/deactivate")
        assert d.status_code == 200
        assert d.json()["deactivated_at"] is not None

        r2 = await _register(c, code, "someuser")
        assert r2.status_code == 410


@pytest.mark.asyncio
async def test_register_unknown_code_404(db: AsyncSession, actors: Actors) -> None:
    async with await ac() as c:
        r = await _register(c, "vh_nonexistent", "someuser")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_register_expired_invite_410(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post(
            "/api/v1/invites",
            json={"expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
        )
        code = r.json()["code"]
        r2 = await _register(c, code, "someuser")
        assert r2.status_code == 410


# --- Username: коллизии и валидация ---


@pytest.mark.asyncio
async def test_register_username_taken_409(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post("/api/v1/invites", json={})
        code = r.json()["code"]

        # alice уже есть в системе
        r2 = await _register(c, code, "alice")
        assert r2.status_code == 409
        # KC-аккаунт не создавался (проверка до KC)
        assert len(actors.kc.created) == 0


@pytest.mark.asyncio
async def test_register_kc_username_conflict_409(db: AsyncSession, actors: Actors) -> None:
    """Username свободен в системе, но занят в Keycloak → 409 (без мусора)."""
    actors.kc.existing_usernames.add("ivan")
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post("/api/v1/invites", json={})
        code = r.json()["code"]
        r2 = await _register(c, code, "ivan")
        assert r2.status_code == 409


@pytest.mark.asyncio
async def test_register_kc_down_502(db: AsyncSession, actors: Actors) -> None:
    """KC недоступен → 502, код не потрачен (транзакция не прошла)."""
    actors.kc.fail_create_with = 502
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post("/api/v1/invites", json={"max_uses": 1})
        code = r.json()["code"]

        r2 = await _register(c, code, "someuser")
        assert r2.status_code == 502

    # код не потрачен — после восстановления работает
    actors.kc.fail_create_with = None
    async with await ac() as c:
        r3 = await _register(c, code, "someuser")
        assert r3.status_code == 201


@pytest.mark.asyncio
async def test_register_compensates_kc_on_race_loss(db: AsyncSession, actors: Actors) -> None:
    """Гонка: код исчерпан ПОСЛЕ предварительной проверки, но ДО conditional UPDATE.

    Эмулируем трату кода в момент create_user (между проверкой и потреблением):
    регистрация падает 410, KC-аккаунт удаляется компенсацией (§5).
    """
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post("/api/v1/invites", json={"max_uses": 1})
        code = r.json()["code"]

    from app.services.invites import hash_invite_code

    async def _spend_code() -> None:
        """Другой запрос потратил последний слот кода."""
        invite = (
            await db.execute(select(Invite).where(Invite.code_hash == hash_invite_code(code)))
        ).scalar_one()
        invite.uses_count = 1
        await db.commit()

    actors.kc.on_create = _spend_code

    async with await ac() as c:
        r2 = await _register(c, code, "racer")
        assert r2.status_code == 410

    # KC-аккаунт был создан и затем удалён компенсацией
    assert len(actors.kc.created) == 0
    assert len(actors.kc.deleted) == 1

    # пользователь в системе не создан
    found = (await db.execute(select(User).where(User.username == "racer"))).scalars().all()
    assert found == []


@pytest.mark.asyncio
async def test_register_invalid_username_422(db: AsyncSession, actors: Actors) -> None:
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post("/api/v1/invites", json={})
        code = r.json()["code"]
        assert (await _register(c, code, "we")).status_code == 422  # слишком короткий
        assert (await _register(c, code, "bad user!")).status_code == 422
        assert (await _register(c, code, "ok-user", password="short")).status_code == 422


@pytest.mark.asyncio
async def test_register_extra_fields_forbidden(db: AsyncSession, actors: Actors) -> None:
    """extra=forbid: попытка прокинуть is_bot/is_platform_admin — 422 (§5)."""
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post("/api/v1/invites", json={})
        code = r.json()["code"]
        r2 = await c.post(
            "/api/v1/auth/register",
            json={"invite_code": code, "username": "hacker", "password": "s3cret-pass", "is_platform_admin": True},
        )
        assert r2.status_code == 422


@pytest.mark.asyncio
async def test_register_response_has_no_password(db: AsyncSession, actors: Actors) -> None:
    """Пароль нигде не возвращается и не хранится в системе (его хранит KC)."""
    actors.act_as("admin")
    async with await ac() as c:
        r = await c.post("/api/v1/invites", json={})
        code = r.json()["code"]
        r2 = await _register(c, code, "safe-user")
        assert r2.status_code == 201
        assert "password" not in r2.json()

    raw = (await db.execute(select(User).where(User.username == "safe-user"))).scalar_one()
    assert not hasattr(raw, "password")
    _ = json  # импорт для читаемости ассертов выше
