"""Пользователи: /users/me (GET/PATCH), поиск /users?q= (§12 — для чатов/участников, люди и боты)."""

from typing import Annotated

from app.api.deps import UserDep
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserOut, UserUpdateIn
from app.services import profile as profile_service
from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["users"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("/users/me", response_model=UserOut)
async def read_me(me: UserDep) -> UserOut:
    return UserOut.model_validate(me)


@router.patch("/users/me", response_model=UserOut)
async def update_me(body: UserUpdateIn, me: UserDep, db: DbDep) -> UserOut:
    """Персональные данные редактируются только в системе (§5): из JWT ничего не берётся.

    Частичное обновление: отсутствующее поле не меняется, явно переданный null —
    очистить. Аватар: avatar_file_id должен быть `ready`-файлом пользователя
    (image), проверяется в сервисе.
    """
    updated = await profile_service.update_profile(
        db, user_id=me.id, updates=body.model_dump(exclude_unset=True)
    )
    return UserOut.model_validate(updated)


@router.get("/users", response_model=list[UserOut])
async def search_users(q: str, me: UserDep, db: DbDep) -> list[UserOut]:
    """Поиск людей и ботов по username/display_name (is_bot в ответе, §12)."""
    pattern = f"%{q}%"
    stmt = (
        select(User)
        .where(
            or_(User.username.ilike(pattern), User.display_name.ilike(pattern)),
            User.id != me.id,
        )
        .limit(20)
    )
    found = (await db.scalars(stmt)).all()
    return [UserOut.model_validate(u) for u in found]
