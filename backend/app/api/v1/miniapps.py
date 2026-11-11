"""Mini-apps: handoff-роуты (Docs/concept.md §11, §12).

POST /miniapps/{bot_id}/code — one-time код (JWT; участник чата с ботом).
POST /miniapps/token — обмен кода на mat_-токен (TTL 15 мин, хэш в Valkey).
UI mini-apps не строится — только каркас (§11).
"""

from typing import Annotated

from app.api.deps import UserDep
from app.db.session import get_db
from app.models.chat import ChatMember
from app.models.user import User
from app.services import miniapps
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["miniapps"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


class CodeIn(BaseModel):
    """POST /miniapps/token — обмен one-time кода (§11)."""

    code: str = Field(min_length=8, max_length=255)


class CodeOut(BaseModel):
    """Ответ POST /miniapps/{bot_id}/code (§11)."""

    code: str
    expires_in: int  # сек до истечения кода


class MiniappTokenOut(BaseModel):
    """Ответ POST /miniapps/token (§11): mat_-токен, без refresh."""

    token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    bot_id: str


async def _require_shared_chat_with_bot(db: AsyncSession, user_id: str, bot_id: str) -> None:
    """Пользователь должен состоять хотя бы в одном чате с этим ботом (§11)."""
    bot_user = await db.get(User, bot_id)
    if bot_user is None or not bot_user.is_bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "bot not found")

    shared = await db.scalar(
        select(ChatMember.user_id).where(
            ChatMember.user_id == user_id,
            ChatMember.chat_id.in_(
                select(ChatMember.chat_id).where(ChatMember.user_id == bot_id)
            ),
        )
    )
    if shared is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no shared chat with this bot")


@router.post("/miniapps/{bot_id}/code", response_model=CodeOut, status_code=201)
async def issue_miniapp_code(bot_id: str, me: UserDep, db: DbDep) -> CodeOut:
    """One-time код для handoff в iframe (§11): TTL 60 c, привязан к user+bot.

    Только участник какого-либо чата с ботом. Отсутствующий Valkey — 503
    (handoff без хранилища кодов невозможен).
    """
    await _require_shared_chat_with_bot(db, me.id, bot_id)
    try:
        code = await miniapps.create_code(user_id=me.id, bot_id=bot_id)
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "valkey unavailable") from None
    return CodeOut(code=code, expires_in=miniapps.CODE_TTL_SECONDS)


@router.post("/miniapps/token", response_model=MiniappTokenOut, status_code=201)
async def exchange_miniapp_token(body: CodeIn, db: DbDep) -> MiniappTokenOut:
    """Обмен кода на скоупед mat_-токен (§11): TTL 15 мин, без refresh.

    Код одноразовый (GETDEL): повторный обмен тем же кодом — 401.
    """
    session = await miniapps.consume_code(body.code)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or used code")

    user_id = str(session["user_id"])
    bot_id = str(session["bot_id"])

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user inactive")

    token = miniapps.generate_mat_token()
    try:
        await miniapps.store_mat_token(token=token, user_id=user_id, bot_id=bot_id)
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "valkey unavailable") from None
    return MiniappTokenOut(
        token=token,
        expires_in=miniapps.TOKEN_TTL_SECONDS,
        user_id=user_id,
        bot_id=bot_id,
    )
