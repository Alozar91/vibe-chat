"""Зависимости FastAPI: текущий пользователь из JWT Keycloak или mat_-токена (§5.4, §11)."""

from typing import Annotated

from app.core.security import AuthContext, require_auth
from app.db.session import get_db
from app.models.user import User
from app.services.users import upsert_user_by_sub
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession


async def current_user(
    ctx: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """JWT → локальный User (upsert при первом входе); mat_-токен → User из БД (§11).

    Деактивированный — 403 (§6). mat_-сессия действует от имени существующего
    пользователя (upsert не нужен — он уже был при JWT-логине).
    """
    if ctx.is_miniapp:
        user = await db.get(User, ctx.mat_user_id)
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "account deactivated")
        return user

    user = await upsert_user_by_sub(
        db,
        sub=ctx.sub,
        preferred_username=ctx.preferred_username,
    )
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account deactivated")
    return user


type UserDep = Annotated[User, Depends(current_user)]
