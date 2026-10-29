import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from app.config import get_settings
from app.core.timeutil import utcnow
from app.db.session import session_factory
from app.models import Device, File, Message, OutboxEvent

logger = logging.getLogger("vibe.jobs")

INTERVALS_SECONDS = {
    "outbox_cleanup": 3600,
    "message_retention": 3600,
    "file_cleanup": 600,
    "device_cleanup": 86400,
    "keycloak_sync": 3600,
    "av_scan": 300,
    "thumbnails": 60,
}

_last_run: dict[str, float] = {}


async def run_jobs() -> None:
    logger.info("Планировщик периодических задач запущен")
    while True:
        try:
            now = asyncio.get_event_loop().time()
            for job, interval in INTERVALS_SECONDS.items():
                if now - _last_run.get(job, 0.0) >= interval:
                    _last_run[job] = now
                    await _run_job(job)
        except Exception:
            logger.exception("Ошибка периодической задачи")
        await asyncio.sleep(30)


async def _run_job(job: str) -> None:
    settings = get_settings()
    if job == "outbox_cleanup":
        await cleanup_outbox(settings.outbox_retention_days)
    elif job == "message_retention":
        if settings.message_retention_days > 0:
            await cleanup_messages(settings.message_retention_days)
    elif job == "file_cleanup":
        await cleanup_orphan_files()
    elif job == "device_cleanup":
        await cleanup_devices()
    elif job == "keycloak_sync" and settings.keycloak_sync_enabled:
        from worker.sync import sync_users_from_keycloak

        await sync_users_from_keycloak()
    elif job == "av_scan" and settings.clamav_host:
        from worker.av import scan_pending_files

        await scan_pending_files()
    elif job == "thumbnails":
        from worker.thumbs import generate_pending_thumbnails

        await generate_pending_thumbnails()


async def cleanup_outbox(retention_days: int) -> None:
    if retention_days <= 0:
        return
    cutoff = utcnow() - timedelta(days=retention_days)
    async with session_factory() as session:
        result = await session.execute(
            sa_delete(OutboxEvent).where(OutboxEvent.published_at.is_not(None), OutboxEvent.created_at < cutoff)
        )
        deleted = getattr(result, "rowcount", 0) or 0
        await session.commit()
        if deleted:
            logger.info("Outbox cleanup: удалено %s", deleted)


async def cleanup_messages(retention_days: int) -> None:
    cutoff = utcnow() - timedelta(days=retention_days)
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(Message)
                .where(Message.created_at < cutoff, Message.type != "system", Message.deleted_at.is_(None))
                .limit(500)
            )
        ).all()
        for message in rows:
            message.deleted_at = utcnow()
            message.body = ""
        await session.commit()
        if rows:
            logger.info("Retention: удалено %s сообщений", len(rows))


async def cleanup_orphan_files() -> None:
    from app.models import MessageAttachment, User

    cutoff = utcnow() - timedelta(hours=24)
    async with session_factory() as session:
        attached = select(MessageAttachment.file_id)
        avatars = select(User.avatar_file_id).where(User.avatar_file_id.is_not(None))
        rows = (
            await session.scalars(
                select(File)
                .where(
                    File.created_at < cutoff,
                    File.id.not_in(attached),
                    File.id.not_in(avatars),
                )
                .limit(200)
            )
        ).all()
        if not rows:
            return
        from app.modules.media.service import _s3_client

        client = _s3_client()
        for file in rows:
            try:
                await asyncio.to_thread(
                    client.delete_object, Bucket=get_settings().s3_bucket, Key=file.storage_key
                )
            except Exception:
                logger.exception("Не удалось удалить объект %s", file.storage_key)
            await session.delete(file)
        await session.commit()
        logger.info("Orphan files cleanup: удалено %s", len(rows))


async def cleanup_devices() -> None:
    cutoff = utcnow() - timedelta(days=90)
    async with session_factory() as session:
        result = await session.execute(sa_delete(Device).where(Device.last_seen_at < cutoff))
        deleted = getattr(result, "rowcount", 0) or 0
        await session.commit()
        if deleted:
            logger.info("Device cleanup: удалено %s", deleted)
