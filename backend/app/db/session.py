"""Асинхронный движок и фабрика сессий."""

from collections.abc import AsyncIterator

from app.core.config import get_settings
from app.db.base import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_settings = get_settings()
engine = create_async_engine(_settings.db_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


__all__ = ["Base", "engine", "SessionLocal", "get_db"]
