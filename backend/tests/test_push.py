"""Тесты пушей (Docs/android.md §3.8, этап 6): токены, fanout, агрегация, version."""

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

import pytest
from app.api.deps import current_user
from app.core import valkey as valkey_core
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.chat import Chat, ChatMember
from app.models.device_token import DeviceToken
from app.models.message import Message
from app.models.user import User
from app.services import push as push_service
from app.services import push_gateway
from app.services.users import upsert_user_by_sub
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class FakeValkey:
    def __init__(self, online: dict[str, int] | None = None) -> None:
        self.store: dict[str, str] = {}
        self.online = online or {}

    async def get(self, key: str) -> str | None:
        if key.startswith("presence:"):
            return str(self.online.get(key, 0))
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> Any:
        self.store[key] = value
        return "OK"

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
async def db(vk: FakeValkey, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncSession]:
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


class FakeGateway:
    """Перехват push_gateway.send: собирает пуши, отдаёт заданные мёртвые токены."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.sent: list[dict[str, Any]] = []
        self.dead: set[str] = set()
        self.enabled = True
        self._original_send = push_gateway.send
        self._original_enabled = push_gateway.push_enabled
        monkeypatch.setattr(push_gateway, "send", self._send)
        monkeypatch.setattr(push_gateway, "push_enabled", lambda: self.enabled)

    async def _send(self, tokens: list[str], *, data: dict[str, str]) -> list[str]:
        for t in tokens:
            self.sent.append({"token": t, "data": data})
        return [t for t in tokens if t in self.dead]


@pytest.fixture
def gw(monkeypatch: pytest.MonkeyPatch) -> FakeGateway:
    return FakeGateway(monkeypatch)


@pytest.fixture
async def actors(db: AsyncSession) -> AsyncIterator[dict[str, User]]:
    """alice (получатель), bob (отправитель), direct-чат, фоновые tokens таблицы."""
    alice = await upsert_user_by_sub(db, sub="sub-a", preferred_username="alice")
    bob = await upsert_user_by_sub(db, sub="sub-b", preferred_username="bob")
    await db.commit()

    async def override_me(db2: Annotated[AsyncSession, Depends(get_db)]) -> User:
        return await db2.get(User, alice.id)

    app.dependency_overrides[current_user] = override_me
    yield {"alice": alice, "bob": bob}


@pytest.fixture
async def direct_chat(db: AsyncSession, actors: dict[str, User]) -> Chat:
    """Direct-чат alice-bob (напрямую через models — создание через сервис не тестируем)."""
    chat = Chat(id="chat-1", type="direct", title=None, created_by=actors["alice"].id)
    db.add(chat)
    db.add(ChatMember(chat_id=chat.id, user_id=actors["alice"].id, role="member"))
    db.add(ChatMember(chat_id=chat.id, user_id=actors["bob"].id, role="member"))
    await db.commit()
    return chat


_msg_seq = 0


async def _make_message(db: AsyncSession, chat_id: str, sender_id: str, text: str = "привет") -> Message:
    """Message c UUIDv7-подобным монотонным id (гекс по маске UUIDv7, старший бит версии)."""
    global _msg_seq
    _msg_seq += 1
    m = Message(
        id=f"01900000-0000-7000-8000-{_msg_seq:012d}",
        chat_id=chat_id,
        sender_id=sender_id,
        type="text",
        text=text,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


# --- REST: токены ---


@pytest.mark.asyncio
async def test_register_and_unregister_token(db: AsyncSession, actors: dict[str, User]) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/push/tokens", json={"token": "fcm-token-aaaa-bbbb", "platform": "android"}
        )
        assert resp.status_code == 201
        row = (await db.scalars(select(DeviceToken))).one()
        assert row.user_id == actors["alice"].id

        # повторная регистрация — upsert (не вторая строка)
        resp = await client.post(
            "/api/v1/push/tokens", json={"token": "fcm-token-aaaa-bbbb", "platform": "android"}
        )
        assert resp.status_code == 201
        assert len((await db.scalars(select(DeviceToken))).all()) == 1

        # чужой/несуществующий токен при удалении — 404
        resp = await client.delete("/api/v1/push/tokens/unknown-token")
        assert resp.status_code == 404

        resp = await client.delete("/api/v1/push/tokens/fcm-token-aaaa-bbbb")
        assert resp.status_code == 204
        assert (await db.scalars(select(DeviceToken))).all() == []


@pytest.mark.asyncio
async def test_register_token_requires_auth(db: AsyncSession) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/push/tokens", json={"token": "x" * 20})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_token_validation(db: AsyncSession, actors: dict[str, User]) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/push/tokens", json={"token": "short"})
        assert resp.status_code == 422
        resp = await client.post(
            "/api/v1/push/tokens", json={"token": "a" * 20, "platform": "windows"}
        )
        assert resp.status_code == 422


# --- Fanout ---


@pytest.mark.asyncio
async def test_push_sent_to_offline_member(
    db: AsyncSession, actors: dict[str, User], direct_chat: Chat, vk: FakeValkey, gw: FakeGateway
) -> None:
    db.add(DeviceToken(token="tok-alice-1", user_id=actors["alice"].id, platform="android"))
    await db.commit()
    msg = await _make_message(db, direct_chat.id, actors["bob"].id)

    await push_service.push_message_to_members(db, direct_chat.id, msg)

    assert len(gw.sent) == 1
    push = gw.sent[0]
    assert push["token"] == "tok-alice-1"
    assert push["data"]["chat_id"] == direct_chat.id
    assert push["data"]["message_id"] == msg.id
    assert push["data"]["count"] == "1"
    # контрольная точка сдвинулась
    tok = await db.get(DeviceToken, "tok-alice-1")
    assert tok.last_pushed_message_id == msg.id


@pytest.mark.asyncio
async def test_no_push_when_online(
    db: AsyncSession, actors: dict[str, User], direct_chat: Chat, vk: FakeValkey, gw: FakeGateway
) -> None:
    """Активный WS → realtime уже доставил, пуш не нужен (§3.5)."""
    db.add(DeviceToken(token="tok-alice-1", user_id=actors["alice"].id, platform="android"))
    await db.commit()
    vk.online["presence:" + actors["alice"].id] = 1
    msg = await _make_message(db, direct_chat.id, actors["bob"].id)

    await push_service.push_message_to_members(db, direct_chat.id, msg)
    assert gw.sent == []


@pytest.mark.asyncio
async def test_no_push_to_sender(
    db: AsyncSession, actors: dict[str, User], direct_chat: Chat, vk: FakeValkey, gw: FakeGateway
) -> None:
    db.add(DeviceToken(token="tok-bob", user_id=actors["bob"].id, platform="android"))
    await db.commit()
    msg = await _make_message(db, direct_chat.id, actors["bob"].id)  # bob сам отправил

    await push_service.push_message_to_members(db, direct_chat.id, msg)
    assert gw.sent == []


@pytest.mark.asyncio
async def test_aggregation_counts_after_cursor(
    db: AsyncSession, actors: dict[str, User], direct_chat: Chat, vk: FakeValkey, gw: FakeGateway
) -> None:
    """Три сообщения после контрольной точки → count=3 в пуше (§3.8 агрегация)."""
    tok = DeviceToken(token="tok-alice-1", user_id=actors["alice"].id, platform="android")
    db.add(tok)
    await db.commit()
    await _make_message(db, direct_chat.id, actors["bob"].id, "раз")
    await _make_message(db, direct_chat.id, actors["bob"].id, "два")
    msg3 = await _make_message(db, direct_chat.id, actors["bob"].id, "три")

    await push_service.push_message_to_members(db, direct_chat.id, msg3)

    assert len(gw.sent) == 1
    assert gw.sent[0]["data"]["count"] == "3"
    # склейка (решение 2026-11-25): body — «N новых сообщений», lines — список последних
    assert gw.sent[0]["data"]["body"] == "3 новых сообщения"
    assert json.loads(gw.sent[0]["data"]["lines"]) == ["раз", "два", "три"]


@pytest.mark.asyncio
async def test_no_push_after_read_catchup(
    db: AsyncSession, actors: dict[str, User], direct_chat: Chat, vk: FakeValkey, gw: FakeGateway
) -> None:
    """Прочитано на другом устройстве (read-курсор догнал) — пуш не нужен."""
    msg1 = await _make_message(db, direct_chat.id, actors["bob"].id, "раз")
    member = (
        await db.scalars(
            select(ChatMember).where(
                ChatMember.chat_id == direct_chat.id, ChatMember.user_id == actors["alice"].id
            )
        )
    ).one()
    member.last_read_message_id = msg1.id  # alice всё прочитала
    await db.commit()

    tok = DeviceToken(token="tok-alice-1", user_id=actors["alice"].id, platform="android")
    db.add(tok)
    await db.commit()

    await push_service.push_message_to_members(db, direct_chat.id, msg1)
    assert gw.sent == []


@pytest.mark.asyncio
async def test_system_message_not_pushed(
    db: AsyncSession, actors: dict[str, User], direct_chat: Chat, vk: FakeValkey, gw: FakeGateway
) -> None:
    db.add(DeviceToken(token="tok-alice-1", user_id=actors["alice"].id, platform="android"))
    await db.commit()
    sys_msg = Message(
        id="01900000-0000-7000-8000-aaaaaaaaaaaa",
        chat_id=direct_chat.id,
        sender_id=None,
        type="system",
        text="название изменено",
        payload={"kind": "rename"},
    )
    db.add(sys_msg)
    await db.commit()

    await push_service.push_message_to_members(db, direct_chat.id, sys_msg)
    assert gw.sent == []


@pytest.mark.asyncio
async def test_dead_tokens_cleaned(
    db: AsyncSession, actors: dict[str, User], direct_chat: Chat, vk: FakeValkey, gw: FakeGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FCM ответил UNREGISTERED → токен удаляется из БД (§3.8)."""
    db.add(DeviceToken(token="tok-dead", user_id=actors["alice"].id, platform="android"))
    db.add(DeviceToken(token="tok-alive", user_id=actors["alice"].id, platform="android"))
    await db.commit()
    gw.dead.add("tok-dead")
    # cleanup_dead_tokens открывает свою сессию — подменяем на тестовую
    async def fake_cleanup(tokens: list[str]) -> None:
        for t in tokens:
            await db.execute(
                __import__("sqlalchemy").delete(DeviceToken).where(DeviceToken.token == t)
            )
        await db.commit()

    monkeypatch.setattr(push_service, "cleanup_dead_tokens", fake_cleanup)

    msg = await _make_message(db, direct_chat.id, actors["bob"].id)
    await push_service.push_message_to_members(db, direct_chat.id, msg)

    remaining = {t.token for t in (await db.scalars(select(DeviceToken))).all()}
    assert remaining == {"tok-alive"}


# --- Version ---


@pytest.mark.asyncio
async def test_app_version_no_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /app/version — без аутентификации, значения из настроек (§3.8)."""
    from app.core.config import Settings

    monkeypatch.setattr(
        "app.api.v1.push.get_settings",
        lambda: Settings(min_app_version="1.0.0", latest_app_version="1.2.0"),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/app/version")
        assert resp.status_code == 200
        assert resp.json() == {"min_version": "1.0.0", "latest_version": "1.2.0"}
