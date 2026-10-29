import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from valkey.asyncio import Valkey

from app.core.errors import bad_request
from app.core.pagination import parse_pagination
from app.core.security import AuthContext
from app.core.valkey import get_valkey
from app.db.session import get_session
from app.modules.auth.dependencies import get_auth_context, require_csrf
from app.modules.users import service as users_service

router = APIRouter(prefix="/v1", tags=["users"], dependencies=[Depends(require_csrf)])


def _uid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise bad_request("user_id: некорректный UUID") from exc


@router.get("/me")
async def get_me(
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    user = await users_service.get_user_or_404(db, ctx.user_id)
    return users_service.serialize_user(user, include_contacts=True)


@router.patch("/me")
async def patch_me(
    payload: dict,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
    valkey: Valkey = Depends(get_valkey),
) -> dict:
    user = await users_service.get_user_or_404(db, ctx.user_id)
    updated = await users_service.update_profile(db, valkey, user, payload)
    return users_service.serialize_user(updated, include_contacts=True)


@router.get("/users/search")
async def search_users(
    q: str = Query(min_length=1, max_length=100),
    limit: int | None = Query(default=None, ge=1, le=100),
    offset: int | None = Query(default=None, ge=0),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    limit_value, offset_value = parse_pagination(limit, offset, default=20)
    users, next_offset = await users_service.search_users(db, q, limit_value, offset_value)
    return {
        "items": [users_service.serialize_user(u) for u in users],
        "next_offset": next_offset,
    }


@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    target = await users_service.get_user_or_404(db, _uid(user_id))
    include_contacts = target.id == ctx.user_id or ctx.role in ("owner", "admin")
    return users_service.serialize_user(target, include_contacts=include_contacts)
