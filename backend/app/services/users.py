"""Upsert пользователей при первом входе (Docs/concept.md §5.4)."""

from uuid import uuid4

from app.models.user import User
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


async def upsert_user_by_sub(
    db: AsyncSession,
    *,
    sub: str,
    preferred_username: str,
) -> User:
    """Находит пользователя по keycloak_sub; при отсутствии — создаёт.

    Keycloak — только идентификация/аутентификация (§5): персональные данные
    (имя, фамилия, почта, display_name) из JWT не берутся и не обновляются —
    они живут в системе и редактируются через PATCH /users/me. Из токена
    используется только `preferred_username` как начальный username —
    технический логин, не персональные данные.

    Коллизия username (уже занят другим sub) — суффикс (§6).
    """
    existing = await db.scalar(select(User).where(User.keycloak_sub == sub))
    if existing is not None:
        return existing

    base_username = preferred_username
    username = base_username
    suffix = 0
    # Проверяем коллизии username; на гонку двух параллельных upsert'ов отвечает UNIQUE-констрейнт.
    while await db.scalar(select(User.id).where(User.username == username)) is not None:
        suffix += 1
        username = f"{base_username}-{suffix}"

    stmt = (
        pg_insert(User)
        .values(
            id=str(uuid4()),
            keycloak_sub=sub,
            username=username,
            # display_name по умолчанию = username; персональные поля (§5) — NULL,
            # заполняются пользователем через PATCH /users/me
            display_name=username,
            is_bot=False,
            is_platform_admin=False,
            is_active=True,
        )
        .on_conflict_do_nothing(index_elements=["keycloak_sub"])
    )
    await db.execute(stmt)
    await db.commit()

    user = await db.scalar(select(User).where(User.keycloak_sub == sub))
    assert user is not None  # только что вставили
    return user
