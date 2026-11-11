"""Точка входа FastAPI."""

from app.core.config import get_settings
from fastapi import FastAPI

settings = get_settings()

app = FastAPI(
    title="Vibe Chat API",
    version="0.1.0",
    docs_url="/docs",
)

from app.api.v1 import chats, health, messages, realtime, users  # noqa: E402

app.include_router(health.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(chats.router, prefix="/api/v1")
app.include_router(messages.router, prefix="/api/v1")
app.include_router(messages.files_router, prefix="/api/v1")
app.include_router(realtime.router, prefix="/api/v1")
