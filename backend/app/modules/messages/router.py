import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from valkey.asyncio import Valkey

from app.core.errors import bad_request
from app.core.ratelimit import check_limit
from app.core.security import AuthContext
from app.core.valkey import get_valkey
from app.db.session import get_session
from app.modules.auth.dependencies import get_auth_context, require_csrf
from app.modules.chats.service import require_member
from app.modules.messages import service as messages_service

router = APIRouter(
    prefix="/v1/chats/{chat_id}/messages", tags=["messages"], dependencies=[Depends(require_csrf)]
)


class MessageSend(BaseModel):
    model_config = {"extra": "forbid"}

    body: str = ""
    attachments: list[str] = Field(default_factory=list)
    reply_to_seq: int | None = None
    forward: list[dict] = Field(default_factory=list)


class MessageEdit(BaseModel):
    model_config = {"extra": "forbid"}

    body: str


def _chat_id(chat_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(chat_id)
    except ValueError as exc:
        raise bad_request("chat_id: некорректный UUID") from exc


def _seq(seq: int) -> int:
    if seq < 0:
        raise bad_request("seq: неотрицательное число")
    return seq


@router.post("")
async def send_message(
    chat_id: str,
    payload: MessageSend,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
    valkey: Valkey = Depends(get_valkey),
) -> dict:
    await check_limit(valkey, "messages", str(ctx.user_id), limit=60, window_seconds=60)
    chat, member = await require_member(db, _chat_id(chat_id), ctx.user_id)
    idem_key = request.headers.get("Idempotency-Key") or None
    if idem_key and len(idem_key) > 64:
        raise bad_request("Idempotency-Key: до 64 символов")
    message, created = await messages_service.send_message(
        db,
        valkey,
        chat,
        member,
        ctx.user_id,
        payload.model_dump(),
        idem_key,
    )
    return message


@router.get("")
async def list_messages(
    chat_id: str,
    limit: int | None = Query(default=None, ge=1, le=100),
    before_seq: int | None = Query(default=None, ge=0),
    after_seq: int | None = Query(default=None, ge=0),
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    chat, _ = await require_member(db, _chat_id(chat_id), ctx.user_id)
    return await messages_service.list_messages(
        db, chat, ctx.user_id, limit or 50, before_seq, after_seq
    )


@router.get("/{seq}")
async def get_message(
    chat_id: str,
    seq: int,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    chat, _ = await require_member(db, _chat_id(chat_id), ctx.user_id)
    return await messages_service.get_message(db, chat, ctx.user_id, _seq(seq))


@router.patch("/{seq}")
async def edit_message(
    chat_id: str,
    seq: int,
    payload: MessageEdit,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
    valkey: Valkey = Depends(get_valkey),
) -> dict:
    chat, member = await require_member(db, _chat_id(chat_id), ctx.user_id)
    return await messages_service.edit_message(
        db, valkey, chat, member, _seq(seq), ctx.user_id, payload.body
    )


@router.delete("/{seq}")
async def delete_message(
    chat_id: str,
    seq: int,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
    valkey: Valkey = Depends(get_valkey),
) -> Response:
    chat, member = await require_member(db, _chat_id(chat_id), ctx.user_id)
    await messages_service.delete_message(db, valkey, chat, member, _seq(seq), ctx.user_id)
    return Response(status_code=204)
