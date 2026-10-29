import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import bad_request
from app.core.security import AuthContext
from app.db.session import get_session
from app.modules.auth.dependencies import get_auth_context
from app.modules.search import service as search_service

router = APIRouter(prefix="/v1/search", tags=["search"])


def _opt_uuid(value: str | None, name: str) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise bad_request(f"{name}: некорректный UUID") from exc


def _opt_dt(value: str | None, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise bad_request(f"{name}: ISO 8601") from exc


@router.get("")
async def search(
    q: str = Query(min_length=1, max_length=200),
    type: str = Query(default="messages"),
    chat_id: str | None = Query(default=None),
    author_id: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    cid = _opt_uuid(chat_id, "chat_id")
    aid = _opt_uuid(author_id, "author_id")
    df = _opt_dt(date_from, "date_from")
    dt = _opt_dt(date_to, "date_to")
    if type == "messages":
        return await search_service.search_messages(db, ctx.user_id, q, cid, aid, df, dt, limit, offset)
    if type == "users":
        return await search_service.search_users(db, q, limit, offset)
    if type == "chats":
        return await search_service.search_chats(db, ctx.user_id, q, limit, offset)
    raise bad_request("type: messages|chats|users")
