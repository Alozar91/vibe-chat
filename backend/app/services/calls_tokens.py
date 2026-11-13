"""Room-токены LiveKit (§17): скоупед JWT для внешней медиа-подсистемы.

Третье исключение из «бэкенд не выдаёт токены» (§4): не аутентификация
пользователя, а авторизация в конкретный ресурс — комната-звонок,
TTL ~10 мин, grant'ы publish/subscribe. Подпись HS256 API-key/secret
LiveKit; python server SDK не нужен — обычный JWT (HS256).

Контракт claim'ов LiveKit (VideoGrant):
  iss = api_key, sub = identity (user_id), exp, aud = "livekit"?? — нет:
  LiveKit ожидает { iss: api_key, sub: identity, jti: room??, video: grants }.
  Фактическая форма: payload = { iss: api_key, sub: identity,
  video: { room, roomJoin: True, canPublish, canSubscribe, canPublishData } },
  подпись HS256 секретом, заголовок kid = api_key.
"""

import time
from typing import Any

import jwt  # PyJWT — уже в зависимостях (JWKS-валидация Keycloak)
from app.core.config import get_settings


class LiveKitNotConfigured(Exception):
    """APP_LIVEKIT_API_KEY/SECRET не заданы — звонки выключены (503)."""


def _grants(room: str) -> dict[str, Any]:
    return {
        "room": room,
        "roomJoin": True,
        "canPublish": True,
        "canSubscribe": True,
        "canPublishData": True,
    }


def issue_room_token(*, user_id: str, room: str, ttl_seconds: int = 600) -> str:
    """Room-JWT: identity = user_id, room = call.id (§17). TTL ~10 мин."""
    settings = get_settings()
    if not settings.livekit_api_key or not settings.livekit_api_secret:
        raise LiveKitNotConfigured("livekit is not configured")
    now = int(time.time())
    payload = {
        "iss": settings.livekit_api_key,
        "sub": user_id,
        "iat": now,
        "exp": now + ttl_seconds,
        "video": _grants(room),
    }
    return jwt.encode(payload, settings.livekit_api_secret, algorithm="HS256", headers={"kid": settings.livekit_api_key})
