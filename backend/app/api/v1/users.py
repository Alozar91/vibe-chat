"""Пользователи: /users/me (этап 2 — upsert при первом входе, §5.4)."""

from typing import Annotated

from app.core.security import AuthContext, require_auth
from app.db.session import get_db
from app.schemas.user import UserOut
from app.services.users import upsert_user_by_sub
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["users"])


async def _me(ctx: AuthContext, db: Annotated[AsyncSession, Depends(get_db)]) -> UserOut:
    user = await upsert_user_by_sub(
        db,
        sub=ctx.sub,
        preferred_username=ctx.preferred_username,
        display_name=ctx.claims.get("name"),
    )
    return UserOut.model_validate(user)


@router.get("/users/me", response_model=UserOut)
async def read_me(
    ctx: Annotated[AuthContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserOut:
    return await _me(ctx, db)
