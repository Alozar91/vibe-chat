"""Боты: управление (платформенный админ), токены, long polling (Docs/concept.md §10).

Бот — users.is_bot + bot_profiles. Токен vbt_<random> выдаётся один раз, хранится
только sha256. События — персональный Valkey Stream (retention 24 ч); offset =
Stream ID; отставание → resync: true.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core import valkey
from app.models.bot import BotProfile
from app.models.user import User
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

STREAM_RETENTION_MS = 24 * 3600 * 1000  # 24 ч (§10)
BOT_UPDATES_MAX = 100


def generate_bot_token() -> tuple[str, str]:
    """vbt_<random> → (токен, sha256-хэш). Хэш хранится, токен — один раз (§10)."""
    raw = secrets.token_urlsafe(32)
    token = f"vbt_{raw}"
    return token, hash_bot_token(token)


def hash_bot_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def require_platform_admin(me: User) -> None:
    """Управление ботами — только платформенный админ (§6, §10)."""
    if not me.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "platform admin required")


async def create_bot(
    db: AsyncSession,
    *,
    admin: User,
    username: str,
    display_name: str,
    description: str | None,
) -> tuple[User, BotProfile, str]:
    """Создание бота: users (is_bot, keycloak_sub NULL) + bot_profiles; токен — в ответе (§10)."""
    await require_platform_admin(admin)

    # коллизия username — суффикс (как у людей, §6)
    base = username
    candidate = base
    suffix = 0
    while await db.scalar(select(User.id).where(User.username == candidate)) is not None:
        suffix += 1
        candidate = f"{base}-{suffix}"

    token, token_hash = generate_bot_token()
    bot_user = User(
        id=str(uuid.uuid4()),
        keycloak_sub=None,  # боты не проходят через Keycloak (§6)
        username=candidate,
        display_name=display_name,
        is_bot=True,
        is_active=True,
    )
    db.add(bot_user)
    profile = BotProfile(
        user_id=bot_user.id,
        owner_user_id=admin.id,
        description=description,
        token_hash=token_hash,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(bot_user)
    await db.refresh(profile)
    return bot_user, profile, token


async def list_bots(db: AsyncSession) -> list[tuple[User, BotProfile]]:
    stmt = select(User, BotProfile).join(BotProfile, BotProfile.user_id == User.id)
    rows = (await db.execute(stmt)).all()
    return [(user, profile) for user, profile in rows]


async def get_bot(db: AsyncSession, bot_id: str) -> tuple[User, BotProfile]:
    user = await db.get(User, bot_id)
    profile = await db.get(BotProfile, bot_id)
    if user is None or profile is None or not user.is_bot:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "bot not found")
    return user, profile


async def update_bot(
    db: AsyncSession,
    *,
    admin: User,
    bot_id: str,
    description: str | None = None,
    is_active: bool | None = None,
    miniapp_url: str | None = None,
    miniapp_name: str | None = None,
    description_set: bool = False,
    miniapp_set: bool = False,
) -> tuple[User, BotProfile]:
    """PATCH /bots/{id}: description, is_active, miniapp-поля (§12)."""
    await require_platform_admin(admin)
    bot_user, profile = await get_bot(db, bot_id)
    if description_set:
        profile.description = description
    if is_active is not None:
        bot_user.is_active = is_active
    if miniapp_set:
        profile.miniapp_url = miniapp_url
        profile.miniapp_name = miniapp_name
    await db.commit()
    await db.refresh(bot_user)
    await db.refresh(profile)
    return bot_user, profile


async def regenerate_token(db: AsyncSession, *, admin: User, bot_id: str) -> str:
    """Регенерация: старый токен отклоняется сразу; новый — в ответе (§10)."""
    await require_platform_admin(admin)
    _bot_user, profile = await get_bot(db, bot_id)
    token, token_hash = generate_bot_token()
    profile.token_hash = token_hash
    await db.commit()
    return token


# --- Bot API auth (Bearer vbt_) ---


async def authenticate_bot(db: AsyncSession, authorization: str | None) -> tuple[User, BotProfile]:
    """Bearer vbt_... → (User, BotProfile); иначе 401. Деактивация → 401 сразу (§10)."""
    if not authorization or not authorization.startswith("Bearer vbt_"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bot token required")
    token = authorization.removeprefix("Bearer ")
    token_hash = hash_bot_token(token)
    stmt = select(User, BotProfile).join(BotProfile, BotProfile.user_id == User.id).where(
        BotProfile.token_hash == token_hash
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid bot token")
    user, profile = row
    if not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bot deactivated")
    return user, profile


# --- Long polling: Valkey Streams (§10) ---


async def stream_key(bot_user_id: str) -> str:
    return f"bot_updates:{bot_user_id}"


def _stream_id_lt(a: str, b: str) -> bool:
    """Строгое сравнение Stream ID "ms-seq" числово (не лексикографически)."""

    def parts(x: str) -> tuple[int, int]:
        ms, _, seq = x.partition("-")
        return int(ms), int(seq or 0)

    return parts(a) < parts(b)


async def push_bot_event(bot_user_id: str, event_type: str, data: dict[str, Any]) -> None:
    """Событие в персональный Stream бота (message.new/edited/deleted, member.joined/left).

    Недоступный Valkey не роняет мутацию-источник (та же мягкая деградация, что у pub/sub):
    бот догонит через resync (offset старше retention) или /bot/chats/{id}/messages.
    """
    import contextlib
    import json

    with contextlib.suppress(Exception):
        key = await stream_key(bot_user_id)
        await valkey.get_valkey().xadd(
            key,
            {"event": json.dumps({"type": event_type, "data": data}, ensure_ascii=False)},
            id="*",
        )


async def read_updates(
    *,
    bot_user_id: str,
    offset: str | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Long polling GET /bot/updates: блокирующее чтение Stream (§10).

    offset=None / '0' → читать с начала retention. Offset старше retention →
    resync: true (бот делает полный resync, §10). timeout=0 — неблокирующее чтение.
    """
    client = valkey.get_valkey()
    key = await stream_key(bot_user_id)

    if not offset or offset == "0":
        # с начала: всё, что осталось в retention (MAXLEN при xadd)
        entries = await client.xrange(key, min="-", max="+", count=BOT_UPDATES_MAX)
        return _entries_to_response(entries, next_offset=None, resync=False)

    try:
        # offset вытеснен retention (первый живой ID новее offset) → resync (§10)
        first = await client.xrange(key, min="-", max="+", count=1)
        if first and _stream_id_lt(offset, str(first[0][0])):
            return {"updates": [], "offset": str(first[0][0]), "resync": True}

        if timeout_seconds > 0:
            result = await client.xread(
                {key: offset}, block=timeout_seconds * 1000, count=BOT_UPDATES_MAX
            )
        else:
            result = await client.xread({key: offset}, count=BOT_UPDATES_MAX)

        updates: list[dict[str, Any]] = []
        last_id = offset
        if result:
            for _stream_name, entries in result:
                for entry_id, fields in entries:
                    import json

                    payload = json.loads(str(fields.get("event", "{}")))
                    payload["offset"] = str(entry_id)
                    updates.append(payload)
                    last_id = str(entry_id)
        return {"updates": updates, "offset": last_id, "resync": False}
    except TimeoutError:
        return {"updates": [], "offset": offset, "resync": False}


def _entries_to_response(
    entries: list[Any], *, next_offset: str | None, resync: bool
) -> dict[str, Any]:
    import json

    updates: list[dict[str, Any]] = []
    last_id: str | None = next_offset
    for entry_id, fields in entries:
        payload = json.loads(str(fields.get("event", "{}")))
        payload["offset"] = str(entry_id)
        updates.append(payload)
        last_id = str(entry_id)
    return {"updates": updates, "offset": last_id, "resync": resync}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
