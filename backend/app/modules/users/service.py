import re
import uuid
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from valkey.asyncio import Valkey

from app.core.errors import bad_request, forbidden, not_found
from app.core.timeutil import utcnow
from app.models import User, UserKind, UserRole, UserStatus
from app.modules.users.cache import invalidate_user_cache

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{2,64}$")


async def get_user_or_404(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None or user.is_deleted:
        raise not_found("Пользователь")
    return user


def serialize_user(user: User, *, include_contacts: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(user.id),
        "kind": str(user.kind),
        "username": user.username,
        "full_name": user.full_name,
        "avatar_url": f"/v1/media/{user.avatar_file_id}/url" if user.avatar_file_id else None,
        "title": user.title,
        "status": str(user.status),
    }
    if include_contacts:
        data["email"] = user.email
        data["phone"] = user.phone
        data["role"] = str(user.role)
        data["source"] = user.source
        data["notification_settings"] = user.notification_settings
        data["created_at"] = user.created_at.isoformat()
    return data


async def update_profile(
    session: AsyncSession, valkey: Valkey, user: User, payload: dict[str, Any]
) -> User:
    if "full_name" in payload:
        value = (payload.get("full_name") or "").strip()
        if not value or len(value) > 200:
            raise bad_request("full_name: 1..200 символов")
        user.full_name = value
    if "phone" in payload:
        phone = (payload.get("phone") or "").strip() or None
        if phone and (len(phone) > 32 or not phone.lstrip("+").isdigit()):
            raise bad_request("phone: до 32 символов, цифры и ведущий +")
        user.phone = phone
    if "title" in payload:
        title = (payload.get("title") or "").strip() or None
        if title and len(title) > 200:
            raise bad_request("title: до 200 символов")
        user.title = title
    if "notification_settings" in payload:
        ns = payload.get("notification_settings") or {}
        if not isinstance(ns, dict):
            raise bad_request("notification_settings: объект")
        mode = ns.get("default_mode")
        if mode is not None and mode not in ("all", "mentions", "none"):
            raise bad_request("default_mode: all|mentions|none")
        user.notification_settings = {**user.notification_settings, **ns}
    user.updated_at = utcnow()
    await session.commit()
    await invalidate_user_cache(valkey, user.id)
    return user


async def search_users(
    session: AsyncSession, query: str, limit: int, offset: int
) -> tuple[list[User], int | None]:
    pattern = f"%{query}%"
    conditions = [User.full_name.ilike(pattern), User.username.ilike(pattern)]
    if "@" in query:
        conditions.append(User.email.ilike(pattern))
    stmt = (
        select(User)
        .where(User.is_deleted.is_(False))
        .where(or_(*conditions))
        .order_by(User.username)
        .limit(limit + 1)
        .offset(offset)
    )
    rows = (await session.scalars(stmt)).all()
    has_more = len(rows) > limit
    return list(rows[:limit]), offset + limit if has_more else None


async def provision_user_from_claims(session: AsyncSession, claims: dict[str, Any]) -> User:
    sub = claims.get("sub")
    if not sub:
        raise bad_request("Токен без sub")
    user = (await session.scalars(select(User).where(User.keycloak_sub == sub))).one_or_none()
    full_name = (claims.get("name") or claims.get("preferred_username") or "Пользователь").strip()
    email = claims.get("email")
    preferred = claims.get("preferred_username") or sub[:12]
    if user is not None:
        if user.status == UserStatus.DISABLED:
            raise forbidden("Учётная запись отключена")
        changed = False
        if user.full_name != full_name:
            user.full_name = full_name
            changed = True
        if email and user.email != email:
            user.email = email
            changed = True
        if changed:
            user.updated_at = utcnow()
            await session.commit()
        return user

    existing_by_username = (
        await session.scalars(select(User).where(User.username == preferred))
    ).one_or_none()
    username = preferred
    if existing_by_username is not None and existing_by_username.keycloak_sub not in (None, sub):
        username = f"{preferred}_{sub[:6]}"
    elif existing_by_username is not None and existing_by_username.keycloak_sub is None:
        existing_by_username.keycloak_sub = sub
        existing_by_username.source = "ldap"
        existing_by_username.full_name = full_name
        if email and not existing_by_username.email:
            existing_by_username.email = email
        existing_by_username.updated_at = utcnow()
        await session.commit()
        return existing_by_username

    email_free = True
    if email:
        email_owner = (
            await session.scalars(select(User).where(User.email == email))
        ).one_or_none()
        email_free = email_owner is None
    user = User(
        kind=UserKind.HUMAN,
        keycloak_sub=sub,
        username=username,
        full_name=full_name,
        email=email if email_free else None,
        role=UserRole.MEMBER,
        status=UserStatus.ACTIVE,
        source="ldap",
    )
    session.add(user)
    await session.commit()
    return user


async def validate_new_username(session: AsyncSession, username: str) -> str:
    if not USERNAME_RE.match(username):
        raise bad_request("username: 2..64 символа, латиница/цифры/._-")
    existing = (
        await session.scalars(select(User).where(func.lower(User.username) == username.lower()))
    ).one_or_none()
    if existing is not None:
        raise bad_request("username занят")
    return username


async def validate_new_email(session: AsyncSession, email: str | None) -> str | None:
    if email is None:
        return None
    email = email.strip().lower()
    if "@" not in email or len(email) > 255:
        raise bad_request("email некорректен")
    existing = (await session.scalars(select(User).where(User.email == email))).one_or_none()
    if existing is not None:
        raise bad_request("email занят")
    return email


async def create_local_user(
    session: AsyncSession,
    *,
    username: str,
    full_name: str,
    email: str | None,
    keycloak_sub: str,
) -> User:
    user = User(
        kind=UserKind.HUMAN,
        keycloak_sub=keycloak_sub,
        username=username,
        full_name=full_name,
        email=email,
        role=UserRole.MEMBER,
        status=UserStatus.ACTIVE,
        source="local",
    )
    session.add(user)
    await session.commit()
    return user
