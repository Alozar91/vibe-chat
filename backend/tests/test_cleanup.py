"""Тесты файлового cleanup (§8: pending TTL, брошенные ready, защита файлов из сообщений)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.chat import Chat, ChatMember
from app.models.file import File
from app.models.message import Attachment, Message
from app.services import cleanup as cl
from app.services.users import upsert_user_by_sub
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


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


def make_file(fid: str, *, status: str, age_hours: int, uploader: str) -> File:
    return File(
        id=fid,
        status=status,
        bucket="b",
        storage_key=f"files/{fid}",
        size_bytes=10,
        mime_type="text/plain",
        real_mime_type="text/plain" if status == "ready" else None,
        sha256="0" * 64,
        uploader_id=uploader,
        created_at=datetime.now(UTC) - timedelta(hours=age_hours),
    )


@pytest.mark.asyncio
async def test_cleanup_pending_older_than_ttl(db: AsyncSession) -> None:
    alice = await upsert_user_by_sub(db, sub="a", preferred_username="alice")
    fresh = make_file("f-fresh", status="pending", age_hours=1, uploader=alice.id)
    stale = make_file("f-stale", status="pending", age_hours=25, uploader=alice.id)
    db.add_all([fresh, stale])
    await db.commit()

    deleted = await cl.cleanup_pending(db)
    assert deleted == ["f-stale"]

    assert await db.get(File, "f-fresh") is not None
    assert await db.get(File, "f-stale") is None


@pytest.mark.asyncio
async def test_cleanup_orphan_ready_only(db: AsyncSession) -> None:
    """Брошенные ready удаляются; прикреплённые и аватары — нет (§8)."""
    alice = await upsert_user_by_sub(db, sub="a", preferred_username="alice")
    bob = await upsert_user_by_sub(db, sub="b", preferred_username="bob")

    old = 24 * 8  # 8 дней назад
    orphan = make_file("f-orphan", status="ready", age_hours=old, uploader=alice.id)
    attached = make_file("f-attached", status="ready", age_hours=old, uploader=alice.id)
    avatar = make_file("f-avatar", status="ready", age_hours=old, uploader=alice.id)
    db.add_all([orphan, attached, avatar])

    chat = Chat(id="ch-1", type="group", title="T", created_by=alice.id)
    db.add(chat)
    db.add(ChatMember(chat_id="ch-1", user_id=alice.id, role="owner"))
    msg = Message(id="01900000-0000-7000-8000-000000000001", chat_id="ch-1", sender_id=alice.id, type="text", text="x")
    db.add(msg)
    db.add(Attachment(id="att-1", message_id=msg.id, file_id="f-attached", kind="file", file_name="a.txt"))
    bob.avatar_file_id = "f-avatar"
    await db.commit()

    deleted = await cl.cleanup_orphan_ready(db)
    assert deleted == ["f-orphan"], "только брошенный ready удаляется"

    assert await db.get(File, "f-orphan") is None
    assert await db.get(File, "f-attached") is not None, "файл из сообщения защищён"
    assert await db.get(File, "f-avatar") is not None, "аватар защищён"


@pytest.mark.asyncio
async def test_cleanup_protects_files_of_soft_deleted_messages(db: AsyncSession) -> None:
    """Файлы сообщений после soft delete защищены — история рендерится (§8)."""
    alice = await upsert_user_by_sub(db, sub="a", preferred_username="alice")

    attached = make_file("f-del-msg", status="ready", age_hours=24 * 8, uploader=alice.id)
    db.add(attached)
    chat = Chat(id="ch-2", type="group", title="T", created_by=alice.id)
    db.add(chat)
    db.add(ChatMember(chat_id="ch-2", user_id=alice.id, role="owner"))
    msg = Message(
        id="01900000-0000-7000-8000-000000000002",
        chat_id="ch-2",
        sender_id=alice.id,
        type="text",
        text="x",
        deleted_at=datetime.now(UTC),  # soft delete
    )
    db.add(msg)
    db.add(Attachment(id="att-2", message_id=msg.id, file_id="f-del-msg", kind="file", file_name="a.txt"))
    await db.commit()

    deleted = await cl.cleanup_orphan_ready(db)
    assert deleted == []
    assert await db.get(File, "f-del-msg") is not None


@pytest.mark.asyncio
async def test_cleanup_chat_avatar_protected(db: AsyncSession) -> None:
    alice = await upsert_user_by_sub(db, sub="a", preferred_username="alice")
    chat_avatar = make_file("f-chat-ava", status="ready", age_hours=24 * 8, uploader=alice.id)
    db.add(chat_avatar)
    chat = Chat(id="ch-3", type="group", title="T", created_by=alice.id, avatar_file_id="f-chat-ava")
    db.add(chat)
    db.add(ChatMember(chat_id="ch-3", user_id=alice.id, role="owner"))
    await db.commit()

    deleted = await cl.cleanup_orphan_ready(db)
    assert deleted == []


@pytest.mark.asyncio
async def test_cleanup_fresh_ready_not_touched(db: AsyncSession) -> None:
    alice = await upsert_user_by_sub(db, sub="a", preferred_username="alice")
    fresh_ready = make_file("f-fresh-ready", status="ready", age_hours=2, uploader=alice.id)
    db.add(fresh_ready)
    await db.commit()

    result = await cl.run_cleanup(db)
    assert result == {"pending": 0, "orphan_ready": 0}
    assert await db.get(File, "f-fresh-ready") is not None


@pytest.mark.asyncio
async def test_cleanup_pending_with_thumb_key_removes_thumb(db: AsyncSession) -> None:
    """У брошенного ready с thumbnail удаляются оба ключа (строки + Silo-объекты)."""
    alice = await upsert_user_by_sub(db, sub="a", preferred_username="alice")
    orphan = make_file("f-orph-thumb", status="ready", age_hours=24 * 8, uploader=alice.id)
    orphan.thumb_key = "thumbs/f-orph-thumb"
    db.add(orphan)
    await db.commit()

    deleted = await cl.cleanup_orphan_ready(db)
    assert deleted == ["f-orph-thumb"]
