"""Зависимости FastAPI: текущий локальный пользователь из JWT (§5.4)."""

from typing import Annotated

from app.core.security import AuthContext, require_auth
from app.db.session import get_db
from app.models.user import User
from app.services.users import upsert_user_by_sub
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession


async def current_user(
    ctx: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """JWT → локальный User (upsert при первом входе). Деактивированный — 403 (§6)."""
    user = await upsert_user_by_sub(
        db,
        sub=ctx.sub,
        preferred_username=ctx.preferred_username,
        display_name=ctx.claims.get("name"),
    )
    if not user.is_active:
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_403_FORBIDDEN, "account deactivated")
    return user


type UserDep = Annotated[User, Depends(current_user)]
