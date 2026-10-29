import csv
import io
import secrets
import string
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from valkey.asyncio import Valkey

from app.core.audit import log_action
from app.core.errors import bad_request, forbidden, not_found
from app.core.timeutil import utcnow
from app.models import (
    AuditLog,
    Chat,
    LoginEvent,
    Message,
    User,
    UserKind,
    UserRole,
    UserStatus,
)
from app.modules.auth.keycloak import KeycloakAdmin
from app.modules.users.cache import invalidate_user_cache
from app.modules.users.service import (
    get_user_or_404,
    serialize_user,
    validate_new_email,
    validate_new_username,
)


def generate_temp_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
        ):
            return password + "!"


async def require_actor(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise not_found("Пользователь")
    return user


async def list_users(
    session: AsyncSession, limit: int, offset: int, query: str | None
) -> dict[str, Any]:
    last_login = (
        select(LoginEvent.user_id, func.max(LoginEvent.created_at).label("last_login_at"))
        .where(LoginEvent.status == "success")
        .group_by(LoginEvent.user_id)
        .subquery()
    )
    stmt = (
        select(User, last_login.c.last_login_at)
        .join(last_login, last_login.c.user_id == User.id, isouter=True)
        .where(User.is_deleted.is_(False), User.kind == UserKind.HUMAN)
    )
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where((User.username.ilike(pattern)) | (User.full_name.ilike(pattern)))
    stmt = stmt.order_by(User.username).limit(limit + 1).offset(offset)
    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    items = []
    for user, last_login_at in rows[:limit]:
        item = serialize_user(user, include_contacts=True)
        item["last_login_at"] = last_login_at.isoformat() if last_login_at else None
        items.append(item)
    return {"items": items, "next_offset": offset + limit if has_more else None}


async def create_user(
    session: AsyncSession,
    valkey: Valkey,
    actor: User,
    username: str,
    full_name: str,
    email: str | None,
    send_email: bool,
    ip: str | None,
) -> dict[str, Any]:
    username = await validate_new_username(session, username)
    email = await validate_new_email(session, email)
    temp_password = generate_temp_password()
    admin = KeycloakAdmin()
    kc_id = await admin.create_user(username, email, full_name, temp_password)
    from app.modules.users.service import create_local_user

    user = await create_local_user(
        session, username=username, full_name=full_name, email=email, keycloak_sub=kc_id
    )
    email_sent = False
    if send_email and email:
        try:
            await admin.execute_actions_email(kc_id, ["UPDATE_PASSWORD"])
            email_sent = True
        except Exception:
            email_sent = False
    await log_action(
        session,
        actor_id=actor.id,
        action="user.created",
        entity_type="user",
        entity_id=str(user.id),
        metadata={"username": username, "email_sent": email_sent},
        ip=ip,
    )
    await session.commit()
    result = serialize_user(user, include_contacts=True)
    if not email_sent:
        result["temporary_password"] = temp_password
    return result


async def import_users_csv(
    session: AsyncSession,
    valkey: Valkey,
    actor: User,
    csv_text: str,
    ip: str | None,
) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(csv_text))
    created = 0
    failed: list[dict[str, Any]] = []
    for index, row in enumerate(reader, start=2):
        username = (row.get("username") or "").strip()
        full_name = (row.get("full_name") or "").strip()
        email = (row.get("email") or "").strip() or None
        if not username or not full_name:
            failed.append({"row": index, "error": "нужны username и full_name"})
            continue
        try:
            await create_user(session, valkey, actor, username, full_name, email, send_email=False, ip=ip)
            created += 1
        except Exception as exc:
            failed.append({"row": index, "error": str(exc)})
    return {"created": created, "failed": failed}


async def reset_password(
    session: AsyncSession,
    actor: User,
    target_id: uuid.UUID,
    send_email: bool,
    ip: str | None,
) -> dict[str, Any]:
    target = await get_user_or_404(session, target_id)
    if target.kind != UserKind.HUMAN or not target.keycloak_sub:
        raise bad_request("Пользователь без Keycloak-учётки")
    temp_password = generate_temp_password()
    admin = KeycloakAdmin()
    if send_email and target.email:
        await admin.set_password(target.keycloak_sub, temp_password, temporary=True)
        try:
            await admin.execute_actions_email(target.keycloak_sub, ["UPDATE_PASSWORD"])
            await log_action(
                session, actor_id=actor.id, action="user.password_reset", entity_type="user",
                entity_id=str(target.id), metadata={"via": "email"}, ip=ip,
            )
            await session.commit()
            return {"email_sent": True}
        except Exception:
            pass
    await admin.set_password(target.keycloak_sub, temp_password, temporary=True)
    await log_action(
        session, actor_id=actor.id, action="user.password_reset", entity_type="user",
        entity_id=str(target.id), metadata={"via": "temp_password"}, ip=ip,
    )
    await session.commit()
    return {"temporary_password": temp_password}


async def set_user_status(
    session: AsyncSession,
    valkey: Valkey,
    actor: User,
    target_id: uuid.UUID,
    disable: bool,
    ip: str | None,
) -> dict[str, Any]:
    if actor.id == target_id:
        raise bad_request("Нельзя изменить свой статус")
    target = await get_user_or_404(session, target_id)
    if target.kind != UserKind.HUMAN:
        raise bad_request("Статус меняется только для пользователей")
    if target.role == UserRole.OWNER:
        raise forbidden("Владельца организации нельзя отключить")
    if target.role == UserRole.ADMIN and actor.role != UserRole.OWNER:
        raise forbidden("Админа может отключить только владелец")
    from app.modules.auth.sessions import revoke_all

    new_status = UserStatus.DISABLED if disable else UserStatus.ACTIVE
    target.status = new_status
    target.updated_at = utcnow()
    if target.keycloak_sub:
        await KeycloakAdmin().set_enabled(target.keycloak_sub, not disable)
    revoked = await revoke_all(valkey, target.id)
    await invalidate_user_cache(valkey, target.id)
    await log_action(
        session,
        actor_id=actor.id,
        action="user.disabled" if disable else "user.enabled",
        entity_type="user",
        entity_id=str(target.id),
        metadata={"revoked_sessions": revoked},
        ip=ip,
    )
    await session.commit()
    return serialize_user(target, include_contacts=True)


async def stats(session: AsyncSession) -> dict[str, Any]:
    day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    users_total = (
        await session.scalar(
            select(func.count(User.id)).where(User.is_deleted.is_(False), User.kind == UserKind.HUMAN)
        )
    ) or 0
    chats_total = (await session.scalar(select(func.count(Chat.id)).where(Chat.deleted_at.is_(None)))) or 0
    messages_per_day = (
        await session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.created_at >= day_start, Message.deleted_at.is_(None))
        )
    ) or 0
    dau = (
        await session.scalar(
            select(func.count(func.distinct(LoginEvent.user_id))).where(
                LoginEvent.created_at >= day_start, LoginEvent.status == "success"
            )
        )
    ) or 0
    from sqlalchemy import BigInteger, cast

    from app.models import File

    storage_bytes = (
        await session.scalar(
            select(cast(func.coalesce(func.sum(File.size_bytes), 0), BigInteger))
        )
    )
    return {
        "users_total": users_total,
        "chats_total": chats_total,
        "messages_per_day": messages_per_day,
        "dau": dau,
        "storage_bytes": storage_bytes or 0,
    }


async def list_audit(
    session: AsyncSession, limit: int, offset: int
) -> dict[str, Any]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit + 1).offset(offset)
    rows = (await session.scalars(stmt)).all()
    has_more = len(rows) > limit
    items = [
        {
            "id": row.id,
            "actor_id": str(row.actor_id) if row.actor_id else None,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "metadata": row.metadata_,
            "ip": row.ip,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows[:limit]
    ]
    return {"items": items, "next_offset": offset + limit if has_more else None}
