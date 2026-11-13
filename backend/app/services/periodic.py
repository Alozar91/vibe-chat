"""Периодические фоновые задачи: файловый cleanup (§8) + звонки (§17).

Запускается на старте приложения (lifespan); интервалы — константы ниже.
Состояний в процессах нет (§14): задачи только триггерят чистку, состояние — в БД/Silo/LiveKit.
"""

import asyncio
import logging

from app.db.session import SessionLocal
from app.services import calls as call_service
from app.services import cleanup

logger = logging.getLogger("vibe.cleanup")

CLEANUP_INTERVAL_SECONDS = 3600  # раз в час
CALLS_INTERVAL_SECONDS = 15  # ringing-таймаут и осиротевшие active (§17)


async def _cleanup_loop() -> None:
    while True:
        try:
            async with SessionLocal() as db:
                await cleanup.run_cleanup(db)
        except Exception:
            logger.exception("cleanup iteration failed")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


async def _calls_loop() -> None:
    """Сторож звонков: ringing старше 45 сек → ended + call_missed; active без участников → ended."""
    while True:
        try:
            async with SessionLocal() as db:
                closed = await call_service.cleanup_stale_calls(db)
                if closed:
                    logger.info("closed %d stale calls", closed)
        except Exception:
            logger.exception("calls cleanup iteration failed")
        await asyncio.sleep(CALLS_INTERVAL_SECONDS)


def start_background_tasks(app: object) -> list[asyncio.Task[None]]:
    """Создаёт фоновые задачи; вызывается из lifespan."""
    return [
        asyncio.create_task(_cleanup_loop(), name="file-cleanup"),
        asyncio.create_task(_calls_loop(), name="calls-cleanup"),
    ]


def stop_background_tasks(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    # ожидание завершения — не блокирует: отмены обрабатываются задачами сами
