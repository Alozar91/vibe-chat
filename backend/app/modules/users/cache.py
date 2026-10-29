import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from valkey.asyncio import Valkey

from app.core.errors import unauthorized
from app.models import User

AUTH_INFO_PREFIX = "user_auth:"
AUTH_INFO_TTL = 30


async def get_auth_info(session: AsyncSession, valkey: Valkey, user_id: uuid.UUID) -> dict[str, Any]:
    key = AUTH_INFO_PREFIX + str(user_id)
    cached = await valkey.get(key)
    if cached:
        return json.loads(cached)
    user = await session.get(User, user_id)
    if user is None or user.is_deleted:
        raise unauthorized()
    info = {"kind": str(user.kind), "role": str(user.role), "status": str(user.status)}
    await valkey.set(key, json.dumps(info), ex=AUTH_INFO_TTL)
    return info


async def invalidate_user_cache(valkey: Valkey, user_id: uuid.UUID) -> None:
    await valkey.delete(AUTH_INFO_PREFIX + str(user_id))
