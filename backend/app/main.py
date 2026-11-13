"""Точка входа FastAPI."""

import asyncio
import contextlib
from collections.abc import AsyncIterator

from app.core.config import get_settings
from fastapi import FastAPI

settings = get_settings()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # бакет Silo — гарантируется при старте (§8): иначе первая загрузка — NoSuchBucket
    from app.services.files import ensure_bucket
    from app.services.periodic import start_background_tasks, stop_background_tasks

    with contextlib.suppress(Exception):  # недоступный Silo не роняет бэкенд
        await asyncio.to_thread(ensure_bucket)
    tasks = start_background_tasks(app)
    yield
    stop_background_tasks(tasks)


app = FastAPI(
    title="Vibe Chat API",
    version="0.1.0",
    docs_url="/docs",
    lifespan=lifespan,
)

from app.api.v1 import bots, calls, chats, health, invites, messages, miniapps, realtime, users  # noqa: E402

app.include_router(health.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(invites.router, prefix="/api/v1")
app.include_router(invites.admin_router, prefix="/api/v1")
app.include_router(chats.router, prefix="/api/v1")
app.include_router(messages.router, prefix="/api/v1")
app.include_router(messages.files_router, prefix="/api/v1")
app.include_router(calls.router, prefix="/api/v1")
app.include_router(realtime.router, prefix="/api/v1")
app.include_router(bots.admin_router, prefix="/api/v1")
app.include_router(bots.bot_router, prefix="/api/v1")
app.include_router(miniapps.router, prefix="/api/v1")
