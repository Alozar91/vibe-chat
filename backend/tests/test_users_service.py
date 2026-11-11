"""Тесты upsert-логики: первый вход создаёт, повторный — возвращает, коллизия username — суффикс,
инвайт-запись привязывается к KC-sub при первом логине (§5)."""

from collections.abc import AsyncIterator

import pytest
from app.db.base import Base
from app.services.users import upsert_user_by_sub
from sqlalchemy import select
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
    """Первый вход: username от preferred_username; display_name = username;
    персональные поля NULL — из JWT-клеймов ничего не берётся (§5)."""
    user = await upsert_user_by_sub(db_session, sub="sub-1", preferred_username="alice")
    assert user.keycloak_sub == "sub-1"
    assert user.username == "alice"
    assert user.display_name == "alice"
    assert user.first_name is None
    assert user.last_name is None
    assert user.email is None


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


@pytest.mark.asyncio
async def test_invite_record_claimed_on_first_login(db_session: AsyncSession) -> None:
    """Инвайт-запись (keycloak_sub=NULL) привязывается к KC-sub при первом логине, а не дублируется.

    Регрессия: JIT-upsert искал только по keycloak_sub и создавал second-1
    с пустыми персональными данными вместо привязки записи из регистрации (§5).
    """
    from app.models.user import User

    # запись, созданная инвайт-регистрацией: sub ещё NULL, персональные данные заполнены
    db_session.add(
        User(
            id="u-invitee",
            keycloak_sub=None,
            username="carol",
            display_name="Каролина",
            first_name="Каролина",
            last_name="Тест",
            email="carol@example.com",
            is_bot=False,
            is_active=True,
        )
    )
    await db_session.commit()

    user = await upsert_user_by_sub(db_session, sub="sub-carol", preferred_username="carol")
    assert user.id == "u-invitee"  # та же запись, не дубликат
    assert user.keycloak_sub == "sub-carol"
    assert user.display_name == "Каролина"  # персональные данные не затёрты (§5)

    # записей carol — одна
    count = len((await db_session.scalars(select(User).where(User.username == "carol"))).all())
    assert count == 1


@pytest.mark.asyncio
async def test_collision_with_unclaimed_invite_record(db_session: AsyncSession) -> None:
    """username занят, но запись с другим username; suффикс работает и для unclaimed-записей."""

    from app.models.user import User

    db_session.add(
        User(
            id="u-x",
            keycloak_sub=None,
            username="dave",
            display_name="dave",
            is_bot=False,
            is_active=True,
        )
    )
    await db_session.commit()

    # первый логин dave — привязка к существующей записи
    u = await upsert_user_by_sub(db_session, sub="sub-dave", preferred_username="dave")
    assert u.id == "u-x"

    # другой KC-пользователь с тем же preferred_username — суффикс
    u2 = await upsert_user_by_sub(db_session, sub="sub-other", preferred_username="dave")
    assert u2.username == "dave-1"
    assert u2.id != "u-x"
