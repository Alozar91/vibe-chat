import contextlib
import json

from valkey.asyncio import Valkey

from app.config import get_settings

_client: Valkey | None = None


def get_valkey() -> Valkey:
    global _client
    if _client is None:
        _client = Valkey.from_url(get_settings().valkey_url, decode_responses=True)
    return _client


async def publish_event(event: dict) -> None:
    with contextlib.suppress(Exception):
        await get_valkey().publish(
            get_settings().ws_event_channel, json.dumps(event, ensure_ascii=False)
        )


async def close_valkey() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
