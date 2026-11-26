"""Тесты фоновых звонков (§17 D, ветка feature/background-calls):

push-фанат call.ring / call.started / call.cancelled офлайн-участникам —
правила аудитории те же, что у сообщений (§18): исключён инициатор/актор,
онлайн (presence > 0) пропускается, нет токенов — нет пуша; payload data-only.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.core import valkey as valkey_core
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.call import Call
from app.models.chat import Chat, ChatMember
from app.models.device_token import DeviceToken
from app.models.user import User
from app.services import push_gateway
from app.services.calls import cancel_call, cleanup_stale_calls, reject_call, start_call
from app.services.users import upsert_user_by_sub
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


class FakeGateway:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.sent: list[dict[str, Any]] = []
        self.dead: set[str] = set()
        self.enabled = True
        self._original_send = push_gateway.send
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
    alice = await upsert_user_by_sub(db, sub="sub-a", preferred_username="alice")
    alice.display_name = "Алиса"
    bob = await upsert_user_by_sub(db, sub="sub-b", preferred_username="bob")
    await db.commit()
    yield {"alice": alice, "bob": bob}


@pytest.fixture
async def direct_chat(db: AsyncSession, actors: dict[str, User]) -> Chat:
    chat = Chat(id="chat-1", type="direct", title=None, created_by=actors["alice"].id)
    db.add(chat)
    db.add(ChatMember(chat_id=chat.id, user_id=actors["alice"].id, role="member"))
    db.add(ChatMember(chat_id=chat.id, user_id=actors["bob"].id, role="member"))
    await db.commit()
    return chat


@pytest.fixture
async def group_chat(db: AsyncSession, actors: dict[str, User]) -> Chat:
    chat = Chat(id="chat-g", type="group", title="Группа", created_by=actors["alice"].id)
    db.add(chat)
    db.add(ChatMember(chat_id=chat.id, user_id=actors["alice"].id, role="admin"))
    db.add(ChatMember(chat_id=chat.id, user_id=actors["bob"].id, role="member"))
    await db.commit()
    return chat


async def _add_token(db: AsyncSession, user_id: str, token: str) -> None:
    db.add(DeviceToken(token=token, user_id=user_id, platform="android"))
    await db.commit()


# --- call.ring (direct) ---------------------------------------------------


async def test_ring_pushes_offline_callee(
    db: AsyncSession, gw: FakeGateway, actors: dict[str, User], direct_chat: Chat
) -> None:
    await _add_token(db, actors["bob"].id, "tok-bob")
    call, created = await start_call(
        db, actor=actors["alice"], chat_id=direct_chat.id, kind="audio"
    )
    assert created is True
    assert len(gw.sent) == 1
    sent = gw.sent[0]
    assert sent["token"] == "tok-bob"
    assert sent["data"]["type"] == "call.ring"
    assert sent["data"]["call_id"] == call.id
    assert sent["data"]["chat_id"] == direct_chat.id
    assert sent["data"]["caller_id"] == actors["alice"].id
    assert sent["data"]["caller_name"] == "Алиса"
    assert sent["data"]["kind"] == "audio"
    assert sent["data"]["chat_type"] == "direct"


async def test_ring_skips_initiator_and_online(
    db: AsyncSession,
    gw: FakeGateway,
    vk: FakeValkey,
    actors: dict[str, User],
    direct_chat: Chat,
) -> None:
    await _add_token(db, actors["alice"].id, "tok-alice")
    await _add_token(db, actors["bob"].id, "tok-bob")
    vk.online[f"presence:{actors['bob'].id}"] = 2  # bob онлайн — realtime доставит сам
    await start_call(db, actor=actors["alice"], chat_id=direct_chat.id, kind="audio")
    assert gw.sent == []


async def test_ring_silent_without_tokens(
    db: AsyncSession, gw: FakeGateway, actors: dict[str, User], direct_chat: Chat
) -> None:
    await start_call(db, actor=actors["alice"], chat_id=direct_chat.id, kind="audio")
    assert gw.sent == []


async def test_group_starts_pushed(
    db: AsyncSession, gw: FakeGateway, actors: dict[str, User], group_chat: Chat
) -> None:
    await _add_token(db, actors["bob"].id, "tok-bob")
    await start_call(db, actor=actors["alice"], chat_id=group_chat.id, kind="video")
    assert len(gw.sent) == 1
    data = gw.sent[0]["data"]
    assert data["type"] == "call.started"
    assert data["chat_type"] == "group"
    assert data["kind"] == "video"


# --- call.cancelled -------------------------------------------------------


async def test_cancel_pushes_to_ring_audience(
    db: AsyncSession, gw: FakeGateway, actors: dict[str, User], direct_chat: Chat
) -> None:
    await _add_token(db, actors["bob"].id, "tok-bob")
    call, _ = await start_call(db, actor=actors["alice"], chat_id=direct_chat.id, kind="audio")
    assert len(gw.sent) == 1  # ring
    await cancel_call(db, actor=actors["alice"], call_id=call.id)
    assert len(gw.sent) == 2
    assert gw.sent[1]["data"]["type"] == "call.cancelled"
    assert gw.sent[1]["data"]["call_id"] == call.id


async def test_reject_excludes_actor(
    db: AsyncSession, gw: FakeGateway, actors: dict[str, User], direct_chat: Chat
) -> None:
    await _add_token(db, actors["alice"].id, "tok-alice")
    await _add_token(db, actors["bob"].id, "tok-bob")
    call, _ = await start_call(db, actor=actors["alice"], chat_id=direct_chat.id, kind="audio")
    gw.sent.clear()
    await reject_call(db, actor=actors["bob"], call_id=call.id)
    # bob отклонил сам — ему уведомление об отмене не нужно; alice офлайн — получает
    assert len(gw.sent) == 1
    assert gw.sent[0]["token"] == "tok-alice"
    assert gw.sent[0]["data"]["type"] == "call.cancelled"


async def test_ttl_cleanup_pushes_cancelled(
    db: AsyncSession, gw: FakeGateway, actors: dict[str, User], direct_chat: Chat
) -> None:
    await _add_token(db, actors["bob"].id, "tok-bob")
    call, _ = await start_call(db, actor=actors["alice"], chat_id=direct_chat.id, kind="audio")
    # звонок «создан 2 минуты назад» (TTL ринга 45 с)
    stale = await db.get(Call, call.id)
    assert stale is not None
    stale.created_at = datetime.now(UTC) - timedelta(minutes=2)
    await db.commit()
    gw.sent.clear()
    await cleanup_stale_calls(db)
    assert len(gw.sent) == 1
    assert gw.sent[0]["data"]["type"] == "call.cancelled"
    assert gw.sent[0]["data"]["call_id"] == call.id


async def test_push_errors_do_not_break_call(
    db: AsyncSession,
    gw: FakeGateway,
    monkeypatch: pytest.MonkeyPatch,
    actors: dict[str, User],
    direct_chat: Chat,
) -> None:
    async def boom(*args: Any, **kwargs: Any) -> list[str]:
        raise RuntimeError("fcm down")

    monkeypatch.setattr(push_gateway, "send", boom)
    await _add_token(db, actors["bob"].id, "tok-bob")
    call, created = await start_call(
        db, actor=actors["alice"], chat_id=direct_chat.id, kind="audio"
    )
    assert created is True and call.id  # звонок создан, несмотря на ошибку пуша


# токены: регистрация звонков не использует REST-контекст, но прямой select
# проверяет, что фанат ходит по device_tokens, а не по курсорам сообщений


async def test_tokens_table_not_polluted_by_call_push(
    db: AsyncSession, gw: FakeGateway, actors: dict[str, User], direct_chat: Chat
) -> None:
    await _add_token(db, actors["bob"].id, "tok-bob")
    call, _ = await start_call(db, actor=actors["alice"], chat_id=direct_chat.id, kind="audio")
    await cancel_call(db, actor=actors["alice"], call_id=call.id)
    rows = (
        (await db.execute(select(DeviceToken).where(DeviceToken.user_id == actors["bob"].id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0].token == "tok-bob"
