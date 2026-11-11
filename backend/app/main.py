"""Точка входа FastAPI."""

from app.core.config import get_settings
from fastapi import FastAPI

settings = get_settings()

app = FastAPI(
    title="Vibe Chat API",
    version="0.1.0",
    docs_url="/docs",
)

from app.api.v1 import health, users  # noqa: E402

app.include_router(health.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
