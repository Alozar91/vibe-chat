"""Тесты сообщений: отправка, идемпотентность, reply, forward, edit/delete, пагинация, файлы (§6, §7, §8).

Auth подменяется dependency_overrides; S3 (Silo) — моком на уровне boto3-клиента.
"""

import io
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from app.api.deps import current_user
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.file import File
from app.models.user import User
from app.services import files as file_service
from app.services.users import upsert_user_by_sub
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _png_bytes() -> bytes:
    """Валидный 1px PNG, сгенерированный Pillow (сниффинг/тумбнейл в тестах)."""
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), color=(10, 200, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


PNG_1PX = _png_bytes()


@dataclass
class Actors:
    """Тестовые пользователи + переключатель текущего."""

    alice: User
    bob: User
    carol: User
    _override: dict[str, object] = field(default_factory=dict, init=False)

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


async def make_chat(db: AsyncSession, actors: Actors, *members: str) -> str:
    """Групповой чат: alice = owner, остальные — участники."""
    from app.services.chats import create_group

    chat = await create_group(
        db, creator_id=actors.alice.id, title="T", member_ids=[getattr(actors, m).id for m in members]
    )
    return chat.id


# --- Отправка и идемпотентность ---


@pytest.mark.asyncio
async def test_send_text_message(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_chat(db, actors, "bob")
    async with await ac() as c:
        r = await c.post(
            f"/api/v1/chats/{chat_id}/messages",
            json={"text": "Привет 👋", "timezone": "Europe/Moscow"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["text"] == "Привет 👋"
        assert body["type"] == "text"
        assert body["sender_id"] == actors.alice.id
        assert body["timezone"] == "Europe/Moscow"
        assert body["attachments"] == []
        # id — UUIDv7 (версия 7 в первом ниббле)
        assert body["id"][14] == "7"


@pytest.mark.asyncio
async def test_idempotent_send_with_key(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_chat(db, actors, "bob")
    key = "11111111-1111-4111-8111-111111111111"
    async with await ac() as c:
        r1 = await c.post(
            f"/api/v1/chats/{chat_id}/messages",
            json={"text": "раз"},
            headers={"Idempotency-Key": key},
        )
        assert r1.status_code == 201
        r2 = await c.post(
            f"/api/v1/chats/{chat_id}/messages",
            json={"text": "раз"},
            headers={"Idempotency-Key": key},
        )
        assert r2.status_code == 201
        assert r2.json()["id"] == r1.json()["id"], "повтор с тем же ключом — то же сообщение"

        # другой ключ → новое сообщение
        r3 = await c.post(
            f"/api/v1/chats/{chat_id}/messages",
            json={"text": "два"},
            headers={"Idempotency-Key": "22222222-2222-4222-8222-222222222222"},
        )
        assert r3.json()["id"] != r1.json()["id"]


@pytest.mark.asyncio
async def test_send_requires_membership(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_chat(db, actors, "bob")
    actors.act_as("carol")
    async with await ac() as c:
        r = await c.post(f"/api/v1/chats/{chat_id}/messages", json={"text": "x"})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_send_empty_422(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_chat(db, actors, "bob")
    async with await ac() as c:
        r = await c.post(f"/api/v1/chats/{chat_id}/messages", json={"text": None})
        assert r.status_code == 422


# --- Цитирование ---


@pytest.mark.asyncio
async def test_reply_validation(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_chat(db, actors, "bob")
    async with await ac() as c:
        r = await c.post(f"/api/v1/chats/{chat_id}/messages", json={"text": "base"})
        base_id = r.json()["id"]

        # валидный reply
        r2 = await c.post(
            f"/api/v1/chats/{chat_id}/messages", json={"text": "ответ", "reply_to_id": base_id}
        )
        assert r2.status_code == 201, r2.text
        assert r2.json()["reply_to_id"] == base_id

        # чужой чат — 422
        other_chat = await make_chat(db, actors, "bob")
        actors.act_as("alice")
        r3 = await c.post(
            f"/api/v1/chats/{other_chat}/messages", json={"text": "x", "reply_to_id": base_id}
        )
        assert r3.status_code == 422


@pytest.mark.asyncio
async def test_cannot_reply_to_system(db: AsyncSession, actors: Actors) -> None:
    """Системные сообщения нельзя цитировать (§6)."""
    from app.models.message import Message

    chat_id = await make_chat(db, actors, "bob")
    system = Message(
        id="01900000-0000-7000-8000-000000000001",
        chat_id=chat_id,
        sender_id=None,
        type="system",
        payload={"event": "chat.created"},
    )
    db.add(system)
    await db.commit()

    async with await ac() as c:
        r = await c.post(
            f"/api/v1/chats/{chat_id}/messages",
            json={"text": "x", "reply_to_id": system.id},
        )
        assert r.status_code == 422


# --- Edit / delete ---


@pytest.mark.asyncio
async def test_edit_own_message(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_chat(db, actors, "bob")
    async with await ac() as c:
        r = await c.post(f"/api/v1/chats/{chat_id}/messages", json={"text": "первый"})
        mid = r.json()["id"]

        r2 = await c.patch(f"/api/v1/messages/{mid}", json={"text": "исправленный"})
        assert r2.status_code == 200, r2.text
        assert r2.json()["text"] == "исправленный"
        assert r2.json()["edited_at"] is not None

        # не-автор не может
        actors.act_as("bob")
        r3 = await c.patch(f"/api/v1/messages/{mid}", json={"text": "hack"})
        assert r3.status_code == 403


@pytest.mark.asyncio
async def test_edit_window_expired(db: AsyncSession, actors: Actors) -> None:
    from app.models.message import Message

    chat_id = await make_chat(db, actors, "bob")
    old = Message(
        id="01900000-0000-7000-8000-000000000002",
        chat_id=chat_id,
        sender_id=actors.alice.id,
        type="text",
        text="старое",
        created_at=datetime.now(UTC) - timedelta(hours=25),
        updated_at=datetime.now(UTC) - timedelta(hours=25),
    )
    db.add(old)
    await db.commit()

    async with await ac() as c:
        r = await c.patch(f"/api/v1/messages/{old.id}", json={"text": "новое"})
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_delete_soft_by_author_and_admin(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_chat(db, actors, "bob", "carol")
    async with await ac() as c:
        r = await c.post(f"/api/v1/chats/{chat_id}/messages", json={"text": "del me"})
        mid = r.json()["id"]

        # не-автор и не-админ — 403
        actors.act_as("carol")
        r2 = await c.delete(f"/api/v1/messages/{mid}")
        assert r2.status_code == 403

        # автор удаляет — soft delete
        actors.act_as("alice")
        r3 = await c.delete(f"/api/v1/messages/{mid}")
        assert r3.status_code == 200
        assert r3.json()["deleted_at"] is not None
        assert r3.json()["text"] is None, "у удалённого текст не отдаётся"

        # в ленте — заглушка
        r4 = await c.get(f"/api/v1/chats/{chat_id}/messages")
        found = [m for m in r4.json() if m["id"] == mid]
        assert found and found[0]["deleted_at"] is not None


@pytest.mark.asyncio
async def test_admin_deletes_other_message(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_chat(db, actors, "bob", "carol")
    async with await ac() as c:
        actors.act_as("carol")
        r = await c.post(f"/api/v1/chats/{chat_id}/messages", json={"text": "spam"})
        mid = r.json()["id"]

        actors.act_as("alice")  # owner = чат-админ
        r2 = await c.delete(f"/api/v1/messages/{mid}")
        assert r2.status_code == 200
        assert r2.json()["deleted_at"] is not None


# --- Пересылка ---


@pytest.mark.asyncio
async def test_forward_atomic_to_multiple_chats(db: AsyncSession, actors: Actors) -> None:
    chat1 = await make_chat(db, actors, "bob")
    chat2 = await make_chat(db, actors, "bob", "carol")
    async with await ac() as c:
        r = await c.post(f"/api/v1/chats/{chat1}/messages", json={"text": "распродажа"})
        src_id = r.json()["id"]

        r2 = await c.post(
            f"/api/v1/messages/{src_id}/forward",
            json={"chat_ids": [chat2, chat1]},
            headers={"Idempotency-Key": "fwd-1"},
        )
        assert r2.status_code == 201, r2.text
        copies = r2.json()
        assert len(copies) == 2
        for copy in copies:
            assert copy["text"] == "распродажа"
            assert copy["forward_from_message_id"] == src_id
            assert copy["forward_from_chat_id"] == chat1
            assert copy["forward_snapshot"]["author_user_id"] == actors.alice.id

        # идемпотентность forward: тот же ключ → те же копии
        r3 = await c.post(
            f"/api/v1/messages/{src_id}/forward",
            json={"chat_ids": [chat2, chat1]},
            headers={"Idempotency-Key": "fwd-1"},
        )
        assert r3.status_code == 201
        assert sorted(m["id"] for m in r3.json()) == sorted(m["id"] for m in copies)


@pytest.mark.asyncio
async def test_forward_non_member_target_403_no_partial(db: AsyncSession, actors: Actors) -> None:
    chat1 = await make_chat(db, actors, "bob")
    secret = await make_chat(db, actors, "bob", "carol")  # carol туда не состоит? — состоит; используем напрямую
    # чат, где alice не состоит: создаёт carol со своими участниками
    from app.services.chats import create_group

    foreign = await create_group(db, creator_id=actors.carol.id, title="F", member_ids=[actors.bob.id])
    _ = secret

    async with await ac() as c:
        r = await c.post(f"/api/v1/chats/{chat1}/messages", json={"text": "x"})
        src_id = r.json()["id"]

        r2 = await c.post(
            f"/api/v1/messages/{src_id}/forward", json={"chat_ids": [foreign.id, chat1]}
        )
        assert r2.status_code == 403
        # атомарность: ни одна копия не создана
        r3 = await c.get(f"/api/v1/chats/{chat1}/messages")
        assert all(m["forward_from_message_id"] is None for m in r3.json())


@pytest.mark.asyncio
async def test_forward_copies_attachments(db: AsyncSession, actors: Actors) -> None:
    """Вложения при пересылке копируются (новые files/attachments, тот же storage_key) (§7)."""
    chat1 = await make_chat(db, actors, "bob")
    chat2 = await make_chat(db, actors, "bob")

    file_row = File(
        id="f-111",
        status="ready",
        bucket="vibe-files",
        storage_key="files/f-111",
        size_bytes=len(PNG_1PX),
        mime_type="image/png",
        real_mime_type="image/png",
        sha256="a" * 64,
        uploader_id=actors.alice.id,
    )
    db.add(file_row)
    await db.commit()

    async with await ac() as c:
        r = await c.post(
            f"/api/v1/chats/{chat1}/messages",
            json={
                "text": "фото",
                "attachments": [{"file_id": "f-111", "kind": "image", "file_name": "shot.png"}],
            },
        )
        assert r.status_code == 201, r.text
        src_id = r.json()["id"]

        r2 = await c.post(f"/api/v1/messages/{src_id}/forward", json={"chat_ids": [chat2]})
        assert r2.status_code == 201
        copy = r2.json()[0]
        assert len(copy["attachments"]) == 1
        # file_id тот же (storage_key общий), но attachment новый
        assert copy["attachments"][0]["file_id"] == "f-111"
        assert copy["attachments"][0]["id"] != r.json()["attachments"][0]["id"]


# --- Пагинация ---


@pytest.mark.asyncio
async def test_pagination_keyset(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_chat(db, actors, "bob")
    ids: list[str] = []
    async with await ac() as c:
        for i in range(7):
            r = await c.post(f"/api/v1/chats/{chat_id}/messages", json={"text": f"m{i}"})
            ids.append(r.json()["id"])

        # лента (дефолт): DESC, старые сверху; limit 3 → последние 3
        r1 = await c.get(f"/api/v1/chats/{chat_id}/messages?limit=3")
        got1 = [m["id"] for m in r1.json()]
        assert got1 == ids[4:], "дефолт — последние сообщения, старые сверху"

        # before — страница назад
        r2 = await c.get(f"/api/v1/chats/{chat_id}/messages?limit=3&before={got1[0]}")
        assert [m["id"] for m in r2.json()] == ids[1:4]

        # after — новые (ASC)
        r3 = await c.get(f"/api/v1/chats/{chat_id}/messages?after={ids[0]}&limit=100")
        assert [m["id"] for m in r3.json()] == ids[1:]


@pytest.mark.asyncio
async def test_pagination_around(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_chat(db, actors, "bob")
    ids: list[str] = []
    async with await ac() as c:
        for i in range(9):
            r = await c.post(f"/api/v1/chats/{chat_id}/messages", json={"text": f"m{i}"})
            ids.append(r.json()["id"])

        r = await c.get(f"/api/v1/chats/{chat_id}/messages?around={ids[4]}&limit=3")
        got = [m["id"] for m in r.json()]
        assert ids[4] in got
        assert len(got) == 3


# --- updated_after (дельта edit/delete для реконнекта, §9) ---


@pytest.mark.asyncio
async def test_updated_after_delta(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_chat(db, actors, "bob")
    async with await ac() as c:
        r1 = await c.post(f"/api/v1/chats/{chat_id}/messages", json={"text": "a"})
        r2 = await c.post(f"/api/v1/chats/{chat_id}/messages", json={"text": "b"})
        mid_a, mid_b = r1.json()["id"], r2.json()["id"]
        cursor = r2.json()["updated_at"]

        await c.patch(f"/api/v1/messages/{mid_a}", json={"text": "a2"})

        r3 = await c.get(f"/api/v1/chats/{chat_id}/messages?updated_after={cursor}")
        changed = {m["id"] for m in r3.json()}
        assert mid_a in changed, "отредактированное сообщение в дельте"
        assert mid_b not in changed, "неизменённое — нет"


# --- Файлы: upload-url / complete / url (§8) ---


class _FakeS3:
    """Мок S3-клиента: без реального Silo."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.exceptions = type("Exceptions", (), {"ClientError": Exception})()

    def generate_presigned_url(self, _op: str, Params: dict[str, str], ExpiresIn: int = 0) -> str:  # noqa: N803
        key = Params.get("Key", "")
        if _op == "put_object":
            return f"http://silo.test/put/{key}"
        return f"http://silo.test/get/{key}"

    def head_object(self, Bucket: str, Key: str) -> dict[str, object]:
        if Key not in self.objects:
            raise self.exceptions.ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {"ContentLength": len(self.objects[Key]), "ContentType": "application/octet-stream"}

    def get_object(self, Bucket: str, Key: str, Range: str = "") -> dict[str, object]:
        if Key not in self.objects:
            raise self.exceptions.ClientError({"Error": {"Code": "404"}}, "GetObject")
        # Range игнорируем: отдаём prefix до 64КБ
        return {"Body": io.BytesIO(self.objects[Key][: 64 * 1024])}

    def put_object(self, Bucket: str, Key: str, Body: bytes, ContentType: str = "") -> None:
        self.objects[Key] = Body


@pytest.fixture
def fake_s3() -> Iterator[_FakeS3]:
    client = _FakeS3()
    with (
        patch.object(file_service, "_s3_client", return_value=client),
    ):
        yield client


@pytest.mark.asyncio
async def test_file_upload_flow(db: AsyncSession, actors: Actors, fake_s3: _FakeS3) -> None:
    chat_id = await make_chat(db, actors, "bob")
    fake_s3.objects["files/new-1"] = PNG_1PX

    async with await ac() as c:
        r = await c.post(
            "/api/v1/files/upload-url",
            json={"size": len(PNG_1PX), "mime": "image/png", "sha256": "b" * 64},
        )
        assert r.status_code == 201, r.text
        file_id = r.json()["file_id"]
        assert "put/" in r.json()["upload_url"]
        fake_s3.objects[f"files/{file_id}"] = PNG_1PX

        r2 = await c.post(f"/api/v1/files/{file_id}/complete")
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body["status"] == "ready"
        assert body["real_mime_type"] == "image/png", "sniffing по сигнатуре PNG"
        assert body["thumb_key"] is not None
        assert body["blurhash"] is not None

        # идемпотентный complete
        r3 = await c.post(f"/api/v1/files/{file_id}/complete")
        assert r3.status_code == 200
        assert r3.json()["status"] == "ready"

        # отправка сообщения с вложением
        r4 = await c.post(
            f"/api/v1/chats/{chat_id}/messages",
            json={
                "text": "фото",
                "attachments": [{"file_id": file_id, "kind": "image", "file_name": "px.png"}],
            },
        )
        assert r4.status_code == 201, r4.text
        att = r4.json()["attachments"][0]
        assert att["kind"] == "image"
        assert att["url"].startswith("http")
        assert att["thumb_url"] is not None

        # GET /files/{id}/url — точечная раздача
        r5 = await c.get(f"/api/v1/files/{file_id}/url")
        assert r5.status_code == 200
        assert r5.json()["url"].startswith("http")


@pytest.mark.asyncio
async def test_kind_mime_mismatch_422(db: AsyncSession, actors: Actors, fake_s3: _FakeS3) -> None:
    """kind не совпадает с real_mime_type → 422, а не тихий рассинхрон (§7)."""
    from app.models.file import File as F

    db.add(
        F(
            id="f-222",
            status="ready",
            bucket="vibe-files",
            storage_key="files/f-222",
            size_bytes=4,
            mime_type="text/plain",
            real_mime_type="text/plain",
            sha256="c" * 64,
            uploader_id=actors.alice.id,
        )
    )
    await db.commit()

    chat_id = await make_chat(db, actors, "bob")
    async with await ac() as c:
        r = await c.post(
            f"/api/v1/chats/{chat_id}/messages",
            json={
                "text": "x",
                "attachments": [{"file_id": "f-222", "kind": "image", "file_name": "fake.png"}],
            },
        )
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_svg_is_not_image(db: AsyncSession, actors: Actors) -> None:
    """SVG — file-attachment, не image (§8)."""
    assert file_service.sniff_mime(b"<?xml version='1.0'?><svg>", "image/svg+xml") == "image/svg+xml"
    from app.models.file import File as F

    db.add(
        F(
            id="f-333",
            status="ready",
            bucket="b",
            storage_key="files/f-333",
            size_bytes=26,
            mime_type="image/svg+xml",
            real_mime_type="image/svg+xml",
            sha256="d" * 64,
            uploader_id=actors.alice.id,
        )
    )
    await db.commit()
    chat_id = await make_chat(db, actors, "bob")
    async with await ac() as c:
        r = await c.post(
            f"/api/v1/chats/{chat_id}/messages",
            json={
                "text": "x",
                "attachments": [{"file_id": "f-333", "kind": "image", "file_name": "v.svg"}],
            },
        )
        assert r.status_code == 422, "SVG нельзя как image"

        r2 = await c.post(
            f"/api/v1/chats/{chat_id}/messages",
            json={
                "text": "x",
                "attachments": [{"file_id": "f-333", "kind": "file", "file_name": "v.svg"}],
            },
        )
        assert r2.status_code == 201, "SVG можно как file"


@pytest.mark.asyncio
async def test_pending_file_not_attachable(db: AsyncSession, actors: Actors) -> None:
    from app.models.file import File as F

    db.add(
        F(
            id="f-444",
            status="pending",
            bucket="b",
            storage_key="files/f-444",
            size_bytes=4,
            mime_type="text/plain",
            sha256="e" * 64,
            uploader_id=actors.alice.id,
        )
    )
    await db.commit()
    chat_id = await make_chat(db, actors, "bob")
    async with await ac() as c:
        r = await c.post(
            f"/api/v1/chats/{chat_id}/messages",
            json={
                "text": "x",
                "attachments": [{"file_id": "f-444", "kind": "file", "file_name": "x.txt"}],
            },
        )
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_foreign_file_403(db: AsyncSession, actors: Actors) -> None:
    from app.models.file import File as F

    db.add(
        F(
            id="f-555",
            status="ready",
            bucket="b",
            storage_key="files/f-555",
            size_bytes=4,
            mime_type="text/plain",
            real_mime_type="text/plain",
            sha256="f" * 64,
            uploader_id=actors.bob.id,
        )
    )
    await db.commit()
    chat_id = await make_chat(db, actors, "bob")
    async with await ac() as c:
        r = await c.post(
            f"/api/v1/chats/{chat_id}/messages",
            json={
                "text": "x",
                "attachments": [{"file_id": "f-555", "kind": "file", "file_name": "x.txt"}],
            },
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_timezone_invalid_becomes_null(db: AsyncSession, actors: Actors) -> None:
    chat_id = await make_chat(db, actors, "bob")
    async with await ac() as c:
        r = await c.post(
            f"/api/v1/chats/{chat_id}/messages", json={"text": "x", "timezone": "Mars/Olympus"}
        )
        assert r.status_code == 201
        assert r.json()["timezone"] is None, "невалидный пояс → NULL (§6)"
