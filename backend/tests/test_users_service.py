"""Тесты upsert-логики: первый вход создаёт, повторный — возвращает, коллизия username — суффикс."""

from collections.abc import AsyncIterator

import pytest
from app.db.base import Base
from app.services.users import upsert_user_by_sub
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_first_login_creates(db_session: AsyncSession) -> None:
    user = await upsert_user_by_sub(
        db_session, sub="sub-1", preferred_username="alice", display_name="Alice"
    )
    assert user.keycloak_sub == "sub-1"
    assert user.username == "alice"
    assert user.display_name == "Alice"


@pytest.mark.asyncio
async def test_second_login_returns_same(db_session: AsyncSession) -> None:
    u1 = await upsert_user_by_sub(db_session, sub="sub-1", preferred_username="alice")
    u2 = await upsert_user_by_sub(db_session, sub="sub-1", preferred_username="alice")
    assert u1.id == u2.id


@pytest.mark.asyncio
async def test_username_collision_adds_suffix(db_session: AsyncSession) -> None:
    await upsert_user_by_sub(db_session, sub="sub-1", preferred_username="bob")
    u2 = await upsert_user_by_sub(db_session, sub="sub-2", preferred_username="bob")
    assert u2.username == "bob-1"
