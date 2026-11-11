"""Valkey: клиент, Pub/Sub fanout, presence-счётчик (Docs/concept.md §9).

Состояний в процессах нет (§14): fanout — через Valkey Pub/Sub, presence —
счётчик соединений в Valkey. Redis-пакеты запрещены политикой проекта.
"""

import contextlib
from typing import Any

from app.core.config import get_settings
from valkey import asyncio as valkey_async

_client: valkey_async.Valkey | None = None


def get_valkey() -> valkey_async.Valkey:
    """Ленивый singleton async-клиента (пул соединений внутри)."""
    global _client
    if _client is None:
        _client = valkey_async.Valkey.from_url(
            get_settings().valkey_url, decode_responses=True
        )
    return _client


async def close_valkey() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# --- Pub/Sub (fanout событий, §9) ---


async def publish(channel: str, payload: str) -> None:
    """Публикация события; недоступный Valkey не роняет REST-мутацию (fanout —
    оптимизация доставки, истина — в БД)."""
    with contextlib.suppress(Exception):
        await get_valkey().publish(channel, payload)


async def subscribe_channels(*channels: str) -> Any:
    """Подписка; возвращает PubSub-объект (get_message/punsubscribe — у caller'а)."""
    client = get_valkey()
    pubsub = client.pubsub()
    await pubsub.subscribe(*channels)
    return pubsub


# --- Presence (§9): счётчик живых соединений пользователя ---


PRESENCE_TTL = 60  # сек — страховка на нечистое закрытие (§9)


async def presence_connect(user_id: str) -> int:
    """INCR при подключении; обновляет TTL-страховку. Возвращает текущий счётчик."""
    client = get_valkey()
    key = f"presence:{user_id}"
    count = int(await client.incr(key))
    await client.expire(key, PRESENCE_TTL)
    return count


async def presence_disconnect(user_id: str) -> int:
    """DECR при закрытии. Возвращает текущий счётчик (0 → offline)."""
    client = get_valkey()
    key = f"presence:{user_id}"
    count = int(await client.decr(key))
    if count <= 0:
        await client.delete(key)
        count = 0
    return count


async def presence_touch(user_id: str) -> None:
    """Пинг TTL-страховки живого соединения."""
    await get_valkey().expire(f"presence:{user_id}", PRESENCE_TTL)


async def set_last_seen_if_offline(db: Any, user_id: str) -> None:
    """DECR → 0: пишем users.last_seen_at (§9). DB-объект передаёт caller (своя сессия)."""
    from app.models.user import User
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(db, AsyncSession)
    await db.execute(update(User).where(User.id == user_id).values(last_seen_at=func_now()))
    await db.commit()


def func_now() -> Any:
    from sqlalchemy import func

    return func.now()
