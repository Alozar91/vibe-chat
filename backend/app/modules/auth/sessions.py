import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from valkey.asyncio import Valkey

from app.config import get_settings
from app.core.security import generate_csrf_token, generate_session_id

SESSION_PREFIX = "sess:"
USER_SESSIONS_PREFIX = "user_sess:"


async def create_session(
    valkey: Valkey,
    user_id: uuid.UUID,
    platform: str,
    ip: str | None,
    user_agent: str | None,
    tokens: dict[str, Any],
) -> tuple[str, str]:
    settings = get_settings()
    sid = generate_session_id()
    csrf = generate_csrf_token()
    now = datetime.now(UTC).isoformat()
    data = {
        "user_id": str(user_id),
        "csrf_token": csrf,
        "platform": platform,
        "ip": ip,
        "user_agent": user_agent,
        "created_at": now,
        "last_seen_at": now,
        "tokens": tokens,
    }
    async with valkey.pipeline() as pipe:
        pipe.set(SESSION_PREFIX + sid, json.dumps(data), ex=settings.session_ttl_seconds)
        pipe.sadd(USER_SESSIONS_PREFIX + str(user_id), sid)
        await pipe.execute()
    return sid, csrf


async def get_session_data(valkey: Valkey, sid: str) -> dict[str, Any] | None:
    raw = await valkey.get(SESSION_PREFIX + sid)
    if raw is None:
        return None
    data = json.loads(raw)
    data["last_seen_at"] = datetime.now(UTC).isoformat()
    await valkey.set(SESSION_PREFIX + sid, json.dumps(data), ex=get_settings().session_ttl_seconds)
    return data


async def revoke_session(valkey: Valkey, sid: str) -> bool:
    raw = await valkey.get(SESSION_PREFIX + sid)
    if raw is None:
        return False
    data = json.loads(raw)
    async with valkey.pipeline() as pipe:
        pipe.delete(SESSION_PREFIX + sid)
        pipe.srem(USER_SESSIONS_PREFIX + data["user_id"], sid)
        await pipe.execute()
    return True


async def revoke_all(valkey: Valkey, user_id: uuid.UUID) -> int:
    key = USER_SESSIONS_PREFIX + str(user_id)
    sids = cast(set[str], await cast(Any, valkey).smembers(key))
    if not sids:
        return 0
    async with valkey.pipeline() as pipe:
        for sid in sids:
            pipe.delete(SESSION_PREFIX + sid)
        pipe.delete(key)
        await pipe.execute()
    return len(sids)


async def list_sessions(valkey: Valkey, user_id: uuid.UUID, current_sid: str | None) -> list[dict[str, Any]]:
    sids = cast(set[str], await cast(Any, valkey).smembers(USER_SESSIONS_PREFIX + str(user_id)))
    items = []
    for sid in sids:
        raw = await valkey.get(SESSION_PREFIX + sid)
        if raw is None:
            continue
        data = json.loads(raw)
        items.append(
            {
                "id": sid,
                "platform": data.get("platform"),
                "ip": data.get("ip"),
                "user_agent": data.get("user_agent"),
                "created_at": data.get("created_at"),
                "last_seen_at": data.get("last_seen_at"),
                "current": sid == current_sid,
            }
        )
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return items
