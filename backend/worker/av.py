import asyncio
import contextlib
import logging
import os

from sqlalchemy import select

from app.config import get_settings
from app.db.session import session_factory
from app.models import File

logger = logging.getLogger("vibe.av")


async def clamav_ping() -> bool:
    settings = get_settings()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(settings.clamav_host, settings.clamav_port), timeout=3
        )
    except Exception:
        return False
    try:
        writer.write(b"zPING\0")
        await writer.drain()
        response = await asyncio.wait_for(reader.read(256), timeout=3)
        return b"PONG" in response
    finally:
        writer.close()


async def scan_pending_files() -> None:
    if not await clamav_ping():
        logger.warning("ClamAV недоступен")
        return
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(File).where(File.av_status == "pending").limit(20)
            )
        ).all()
        for file in rows:
            infected = await _scan_file(file.storage_key)
            file.av_status = "infected" if infected else "clean"
        await session.commit()
        if rows:
            logger.info("AV: просканировано %s файлов", len(rows))


async def _scan_file(storage_key: str) -> bool:
    from app.modules.media.service import _s3_client

    client = _s3_client()
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name
    try:
        def _download() -> None:
            with open(tmp_path, "wb") as fh:
                client.download_fileobj(get_settings().s3_bucket, storage_key, fh)

        await asyncio.to_thread(_download)
        reader, writer = await asyncio.open_connection(
            get_settings().clamav_host, get_settings().clamav_port
        )
        try:
            writer.write(b"zINSTREAM\0")
            await writer.drain()
            with open(tmp_path, "rb") as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    writer.write(len(chunk).to_bytes(4, "big") + chunk)
                    await writer.drain()
            writer.write(b"\0\0\0\0")
            await writer.drain()
            response = await asyncio.wait_for(reader.read(4096), timeout=60)
            return b"FOUND" in response
        finally:
            writer.close()
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
