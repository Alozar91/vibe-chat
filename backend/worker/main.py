import asyncio
import logging

from app.config import get_settings
from app.db.session import dispose_engine, init_engine
from app.log import setup_logging
from worker.consumer import run_consumer
from worker.jobs import run_jobs

logger = logging.getLogger("vibe.worker")


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    init_engine()
    logger.info("Worker запускается: env=%s", settings.env)
    try:
        await asyncio.gather(run_consumer(), run_jobs())
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
