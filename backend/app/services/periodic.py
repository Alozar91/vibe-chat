"""Периодические фоновые задачи: файловый cleanup (§8, дорожная карта п.6).

Запускается на старте приложения (lifespan); интервал — CLEANUP_INTERVAL_SECONDS.
Состояний в процессах нет (§14): задача только триггерит чистку, состояние — в БД/Silo.
"""

import asyncio
import logging

from app.db.session import SessionLocal
from app.services import cleanup

logger = logging.getLogger("vibe.cleanup")

CLEANUP_INTERVAL_SECONDS = 3600  # раз в час


async def _cleanup_loop() -> None:
    while True:
        try:
            async with SessionLocal() as db:
                await cleanup.run_cleanup(db)
        except Exception:
            logger.exception("cleanup iteration failed")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


def start_background_tasks(app: object) -> list[asyncio.Task[None]]:
    """Создаёт фоновые задачи; вызывается из lifespan."""
    task = asyncio.create_task(_cleanup_loop(), name="file-cleanup")
    return [task]


def stop_background_tasks(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    # ожидание завершения — не блокирует: отмены обрабатываются задачами сами
