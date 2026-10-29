import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from valkey.asyncio import Valkey

from app.core.errors import bad_request
from app.core.ratelimit import check_limit
from app.core.security import AuthContext
from app.core.valkey import get_valkey
from app.db.session import get_session
from app.modules.auth.dependencies import get_auth_context, require_csrf
from app.modules.media import service as media_service

router = APIRouter(prefix="/v1/media", tags=["media"], dependencies=[Depends(require_csrf)])


class UploadIntent(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    mime_type: str
    size_bytes: int


class UploadComplete(BaseModel):
    model_config = {"extra": "forbid"}

    file_id: str


@router.post("/upload-intents")
async def create_upload_intent(
    payload: UploadIntent,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
    valkey: Valkey = Depends(get_valkey),
) -> dict:
    await check_limit(valkey, "uploads", str(ctx.user_id), limit=20, window_seconds=3600)
    return await media_service.create_upload_intent(
        db, ctx.user_id, payload.name, payload.mime_type, payload.size_bytes
    )


@router.post("/upload-complete")
async def complete_upload(
    payload: UploadComplete,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    try:
        file_id = uuid.UUID(payload.file_id)
    except ValueError as exc:
        raise bad_request("file_id: некорректный UUID") from exc
    return await media_service.complete_upload(db, ctx.user_id, file_id)


@router.get("/{file_id}/url")
async def get_download_url(
    file_id: str,
    variant: str | None = Query(default=None),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    try:
        fid = uuid.UUID(file_id)
    except ValueError as exc:
        raise bad_request("file_id: некорректный UUID") from exc
    return await media_service.get_download_url(db, fid, ctx.user_id)
