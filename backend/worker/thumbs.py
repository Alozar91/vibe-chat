import asyncio
import contextlib
import logging
import os
import tempfile

from sqlalchemy import select

from app.config import get_settings
from app.db.session import session_factory
from app.models import File

logger = logging.getLogger("vibe.thumbs")

THUMB_SIZE = (320, 320)


async def generate_pending_thumbnails(limit: int = 20) -> None:
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(File)
                .where(
                    File.thumbnail_key.is_(None),
                    File.mime_type.like("image/%"),
                    File.av_status != "infected",
                )
                .limit(limit)
            )
        ).all()
        if not rows:
            return
        from app.modules.media.service import _s3_client

        client = _s3_client()
        settings = get_settings()
        for file in rows:
            try:
                thumb_key = await _make_thumbnail(client, settings.s3_bucket, file.storage_key)
                file.thumbnail_key = thumb_key
            except Exception:
                logger.exception("thumbnail не удался: %s", file.id)
        await session.commit()
        if rows:
            logger.info("thumbnail'ы: обработано %s", len(rows))


async def _make_thumbnail(client, bucket: str, storage_key: str) -> str:
    import io

    from PIL import Image

    with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as tmp:
        tmp_path = tmp.name

    def _download() -> None:
        with open(tmp_path, "wb") as fh:
            client.download_fileobj(bucket, storage_key, fh)

    await asyncio.to_thread(_download)
    try:
        def _resize() -> bytes:
            with Image.open(tmp_path) as source:
                img = source.convert("RGB")
                img.thumbnail(THUMB_SIZE)
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=80)
                return buffer.getvalue()

        data = await asyncio.to_thread(_resize)
        thumb_key = f"{storage_key}.thumb.jpg"

        def _upload() -> None:
            client.put_object(Bucket=bucket, Key=thumb_key, Body=data, ContentType="image/jpeg")

        await asyncio.to_thread(_upload)
        return thumb_key
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
