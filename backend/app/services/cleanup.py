"""Файловый cleanup (Docs/concept.md §8, дорожная карта п.6).

Правила:
- pending старше `file_pending_ttl_hours` (24 ч) — удаляются (строка БД + объект Silo).
- ready старше `file_orphan_days` (7 дней), не прикреплённые ни к одному attachment,
  не являющиеся ничьим аватаром (users/chats) — брошенные загрузки, удаляются.
- Cleanup НЕ удаляет файлы, на которые ссылаются существующие сообщения, — даже
  после их soft delete (история должна рендериться).
"""

import logging
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.models.chat import Chat
from app.models.file import File
from app.models.message import Attachment
from app.models.user import User
from sqlalchemy import delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("vibe.cleanup")


def _s3_delete_quiet(storage_keys: list[str]) -> None:
    """Удаление объектов из Silo; недоступность хранилища не роняет чистку БД
    (осиротевший объект соберёт следующий прогон или ручная чистка)."""
    if not storage_keys:
        return
    try:
        from app.core.config import get_settings
        from app.services.files import _s3_client

        client = _s3_client()
        bucket = get_settings().silo_bucket
        client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": k} for k in storage_keys], "Quiet": True},
        )
    except Exception:
        logger.warning("silo unavailable during cleanup; DB rows purged, objects left")


async def cleanup_pending(db: AsyncSession, *, now: datetime | None = None) -> list[str]:
    """Удаляет pending-файлы старше TTL: строка БД + объект Silo (§8)."""
    settings = get_settings()
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=settings.file_pending_ttl_hours)
    stmt = select(File).where(File.status == "pending", File.created_at < cutoff)
    stale = list((await db.scalars(stmt)).all())
    if not stale:
        return []
    keys = [f.storage_key for f in stale]
    await db.execute(delete(File).where(File.id.in_([f.id for f in stale])))
    await db.commit()
    _s3_delete_quiet(keys)
    return [f.id for f in stale]


async def cleanup_orphan_ready(db: AsyncSession, *, now: datetime | None = None) -> list[str]:
    """Удаляет брошенные ready-файлы: не в attachments, не аватары, старше N дней (§8).

    Файлы из существующих сообщений защищены существованием attachment-строки.
    """
    settings = get_settings()
    cutoff = (now or datetime.now(UTC)) - timedelta(days=settings.file_orphan_days)

    used_in_attachments = exists(select(Attachment.id).where(Attachment.file_id == File.id))
    used_as_user_avatar = exists(select(User.id).where(User.avatar_file_id == File.id))
    used_as_chat_avatar = exists(select(Chat.id).where(Chat.avatar_file_id == File.id))

    stmt = select(File).where(
        File.status == "ready",
        File.created_at < cutoff,
        ~used_in_attachments,
        ~used_as_user_avatar,
        ~used_as_chat_avatar,
    )
    orphans = list((await db.scalars(stmt)).all())
    if not orphans:
        return []
    keys = []
    for f in orphans:
        keys.append(f.storage_key)
        if f.thumb_key:
            keys.append(f.thumb_key)
    await db.execute(delete(File).where(File.id.in_([f.id for f in orphans])))
    await db.commit()
    _s3_delete_quiet(keys)
    return [f.id for f in orphans]


async def run_cleanup(db: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """Полный прогон; возвращает количество удалённых файлов по категориям."""
    pending = await cleanup_pending(db, now=now)
    orphan = await cleanup_orphan_ready(db, now=now)
    result = {"pending": len(pending), "orphan_ready": len(orphan)}
    if pending or orphan:
        logger.info("file cleanup: %s", result)
    return result
