"""Инвайт-регистрация (Docs/concept.md §5 «Регистрация пользователей»).

Multi-use коды платформенного админа; KC-аккаунт через Admin API (только
username+password); персональные данные — сразу в PostgreSQL системы.
Потребление кода — атомарный conditional UPDATE (гонка регистраций).
"""

import hashlib
import secrets
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from app.core import valkey
from app.models.invite import Invite
from app.models.user import User
from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

INVITE_PREFIX = "vh_"
# TTL блокировки username в процессе регистрации: защита от двойного
# сабмита формы (двойной клик) и параллельных регистраций с одним username
USERNAME_LOCK_TTL_SECONDS = 120
USERNAME_LOCK_PREFIX = "reg:username-lock:"


def hash_invite_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def generate_invite_code() -> str:
    return f"{INVITE_PREFIX}{secrets.token_urlsafe(24)}"


async def acquire_username_lock(username: str) -> bool:
    """SET NX-блокировка username на время регистрации (Valkey, мягкая деградация).

    Valkey недоступен → разрешаем (UNIQUE-констрейнты и KC 409 всё равно страхуют).
    """
    try:
        client = valkey.get_valkey()
        acquired: Any = await client.set(
            f"{USERNAME_LOCK_PREFIX}{username.lower()}",
            "1",
            nx=True,
            ex=USERNAME_LOCK_TTL_SECONDS,
        )
        return bool(acquired)
    except Exception:
        return True


async def release_username_lock(username: str) -> None:
    with suppress(Exception):
        await valkey.get_valkey().delete(f"{USERNAME_LOCK_PREFIX}{username.lower()}")


async def create_invite(
    db: AsyncSession,
    *,
    admin: User,
    max_uses: int | None,
    expires_at: datetime | None,
) -> tuple[Invite, str]:
    """Создание кода платформенным админом; код в ответе — один раз (как токен бота)."""
    from app.services.bots import require_platform_admin

    await require_platform_admin(admin)
    if max_uses is not None and max_uses < 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "max_uses must be >= 1")

    code = generate_invite_code()
    invite = Invite(
        id=str(uuid.uuid4()),
        code_hash=hash_invite_code(code),
        created_by=admin.id,
        max_uses=max_uses,
        expires_at=expires_at,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return invite, code


def _invite_out(inv: Invite) -> dict[str, Any]:
    return {
        "id": inv.id,
        "max_uses": inv.max_uses,
        "uses_count": inv.uses_count,
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
        "deactivated_at": inv.deactivated_at.isoformat() if inv.deactivated_at else None,
        "created_at": inv.created_at.isoformat(),
    }


async def list_invites(db: AsyncSession, *, admin: User) -> list[dict[str, Any]]:
    from app.services.bots import require_platform_admin

    await require_platform_admin(admin)
    stmt = select(Invite).order_by(Invite.created_at.desc())
    return [_invite_out(inv) for inv in (await db.scalars(stmt)).all()]


async def deactivate_invite(db: AsyncSession, *, admin: User, invite_id: str) -> dict[str, Any]:
    from app.services.bots import require_platform_admin

    await require_platform_admin(admin)
    invite = await db.get(Invite, invite_id)
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invite not found")
    if invite.deactivated_at is None:
        invite.deactivated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(invite)
    return _invite_out(invite)


def _as_utc(dt: datetime) -> datetime:
    """SQLite отдаёт naive (подразумевается UTC); PostgreSQL — aware. Приводим к aware UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _check_invite_usable(invite: Invite) -> None:
    now = datetime.now(UTC)
    if invite.deactivated_at is not None:
        raise HTTPException(status.HTTP_410_GONE, "invite deactivated")
    if invite.expires_at is not None and _as_utc(invite.expires_at) < now:
        raise HTTPException(status.HTTP_410_GONE, "invite expired")
    if invite.max_uses is not None and invite.uses_count >= invite.max_uses:
        raise HTTPException(status.HTTP_410_GONE, "invite exhausted")


def _validate_registration(*, username: str, password: str, email: str | None) -> None:
    """Базовые правила; детальную политику пароля проверяет Keycloak (локальный минимум — 8)."""
    if not (3 <= len(username) <= 255) or not username.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid username")
    if len(password) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "password too short (min 8)")
    if email is not None and ("@" not in email or len(email) > 320):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid email")


async def register(
    db: AsyncSession,
    *,
    invite_code: str | None,
    open_registration: bool,
    username: str,
    password: str,
    first_name: str | None,
    last_name: str | None,
    email: str | None,
    display_name: str | None,
    kc_admin: Any,
) -> User:
    """Полный цикл регистрации (§5): код → KC-аккаунт → локальный пользователь.

    Персональные данные живут только в PostgreSQL; в Keycloak уходят только
    username+password. Порядок (§5): проверка кода → username → KC → атомарное
    потребление кода + локальный пользователь (одна транзакция); при проигрыше
    гонки — компенсирующее удаление KC-аккаунта.

    Код опционален: без кода — открытая регистрация, разрешённая только при
    open_registration=True (env APP_OPEN_REGISTRATION, §5); иначе 422.
    """
    # 1. Валидация входа
    _validate_registration(username=username, password=password, email=email)
    display = display_name or username

    # 2. Код существует и жив (предварительно; финально — атомарно).
    # Код не передан: открытая регистрация разрешена только флагом (§5)
    invite: Invite | None = None
    if invite_code:
        invite = await db.scalar(select(Invite).where(Invite.code_hash == hash_invite_code(invite_code)))
        if invite is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "invite not found")
        _check_invite_usable(invite)
    elif not open_registration:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invite code required")

    # 3. Username не занят в системе (люди и боты в одной таблице, §6)
    if await db.scalar(select(User.id).where(User.username == username)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "username already taken")
    if not await acquire_username_lock(username):
        raise HTTPException(status.HTTP_409_CONFLICT, "username already taken")

    kc_user_id: str | None = None
    try:
        # 4. KC-аккаунт: только username+password (§5)
        kc_user_id = await kc_admin.create_user(username=username, password=password)

        # 5. Атомарное потребление кода (только если передан): conditional UPDATE —
        # проигравший гонку откатится
        if invite is not None:
            stmt = (
                update(Invite)
                .where(
                    Invite.id == invite.id,
                    Invite.deactivated_at.is_(None),
                    (Invite.max_uses.is_(None)) | (Invite.uses_count < Invite.max_uses),
                )
                .values(uses_count=Invite.uses_count + 1)
            )
            result = await db.execute(stmt)
            consumed = getattr(result, "rowcount", 0)
            if not consumed:
                raise HTTPException(status.HTTP_410_GONE, "invite exhausted")

        # 6. Локальный пользователь (та же транзакция): персональные данные здесь (§5)
        user = User(
            id=str(uuid.uuid4()),
            keycloak_sub=None,  # заполнится при первом логине (JIT upsert по sub)
            username=username,
            display_name=display,
            first_name=first_name,
            last_name=last_name,
            email=email,
            is_bot=False,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user
    except HTTPException:
        # компенсация: KC-аккаунт создан, но транзакция не прошла (гонка/ошибка)
        if kc_user_id is not None:
            with suppress(Exception):
                await kc_admin.delete_user(kc_user_id)
        raise
    finally:
        await release_username_lock(username)
