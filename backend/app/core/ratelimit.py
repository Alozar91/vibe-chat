import time

from valkey.asyncio import Valkey

from app.core.errors import rate_limited


def _now_ms() -> int:
    return int(time.time() * 1000)


async def check_limit(
    valkey: Valkey,
    scope: str,
    key: str,
    limit: int,
    window_seconds: int,
) -> None:
    now = _now_ms()
    window_ms = window_seconds * 1000
    member = f"{now}"
    zkey = f"rl:{scope}:{key}:{window_seconds}"
    try:
        pipe = valkey.pipeline()
        pipe.zremrangebyscore(zkey, 0, now - window_ms)
        pipe.zcard(zkey)
        pipe.zadd(zkey, {member: now})
        pipe.expire(zkey, window_seconds)
        results = await pipe.execute()
        count = results[1]
    except Exception:
        return
    if count >= limit:
        raise rate_limited(window_seconds)
