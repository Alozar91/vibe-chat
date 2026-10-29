import secrets
import uuid

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from valkey.asyncio import Valkey

from app.config import get_settings
from app.core.errors import forbidden, unauthorized
from app.core.security import AuthContext, sha256_hex, verify_access_token
from app.core.timeutil import utcnow
from app.core.valkey import get_valkey
from app.db.session import get_session
from app.models import Bot, BotToken, User, UserKind, UserRole, UserStatus
from app.modules.auth import sessions
from app.modules.users.cache import get_auth_info


async def authenticate_bot_token(session: AsyncSession, token: str) -> AuthContext:
    token_hash = sha256_hex(token)
    row = (
        await session.execute(
            select(BotToken, Bot, User)
            .join(Bot, BotToken.bot_id == Bot.user_id)
            .join(User, Bot.user_id == User.id)
            .where(BotToken.token_hash == token_hash, BotToken.revoked_at.is_(None))
        )
    ).first()
    if row is None:
        raise unauthorized("Недействительный токен бота")
    bot_token, bot, user = row
    now = utcnow()
    if bot_token.expires_at is not None and bot_token.expires_at < now:
        raise unauthorized("Токен бота истёк")
    if not bot.is_enabled:
        raise forbidden("Бот отключён")
    if user.kind != UserKind.BOT or user.status != UserStatus.ACTIVE:
        raise forbidden("Бот недоступен")
    bot_token.last_used_at = now
    return AuthContext(
        user_id=user.id,
        kind=UserKind.BOT,
        role=UserRole.MEMBER,
        status=UserStatus.ACTIVE,
        via="bot",
    )


async def get_auth_context(
    request: Request,
    session: AsyncSession = Depends(get_session),
    valkey: Valkey = Depends(get_valkey),
) -> AuthContext:
    auth_header = request.headers.get("Authorization") or ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token.startswith("mt_"):
            return await authenticate_bot_token(session, token)
        claims = await verify_access_token(token)
        user_id = uuid.UUID(claims["sub"])
        info = await get_auth_info(session, valkey, user_id)
        if info["status"] != "active":
            raise forbidden("Учётная запись отключена")
        return AuthContext(
            user_id=user_id,
            kind=UserKind(info["kind"]),
            role=UserRole(info["role"]),
            status=UserStatus(info["status"]),
            via="bearer",
            claims=claims,
        )
    sid = request.cookies.get(get_settings().session_cookie_name)
    if sid:
        data = await sessions.get_session_data(valkey, sid)
        if data:
            user_id = uuid.UUID(data["user_id"])
            info = await get_auth_info(session, valkey, user_id)
            if info["status"] != "active":
                raise forbidden("Учётная запись отключена")
            return AuthContext(
                user_id=user_id,
                kind=UserKind(info["kind"]),
                role=UserRole(info["role"]),
                status=UserStatus(info["status"]),
                via="cookie",
                session_id=sid,
                csrf_token=data.get("csrf_token"),
            )
    raise unauthorized()


def require_csrf(request: Request, ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if ctx.via != "cookie":
        return ctx
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return ctx
    token = request.headers.get("X-CSRF-Token") or ""
    if not ctx.csrf_token or not secrets.compare_digest(token, ctx.csrf_token):
        raise forbidden("CSRF-токен недействителен")
    return ctx
