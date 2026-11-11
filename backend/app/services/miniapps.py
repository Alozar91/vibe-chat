"""Mini-apps: auth handoff каркас (Docs/concept.md §11).

Поток: one-time код (TTL 60 c, привязан к user+bot) → mat_-токен (TTL 15 мин,
opaque, без refresh; хэш — в Valkey). Коды хранятся как есть (одноразовые,
короткоживущие), токены — только sha256-хэшем. mat_-токен действует от имени
пользователя только внутри этого miniapp; продление — повторный handoff.
"""

import contextlib
import hashlib
import json
import secrets
from typing import Any

from app.core import valkey

CODE_TTL_SECONDS = 60
TOKEN_TTL_SECONDS = 900  # 15 мин (§11)
MAT_PREFIX = "mat_"
CODE_PREFIX = "vac_"


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def create_code(*, user_id: str, bot_id: str) -> str:
    """One-time код handoff (§11): TTL 60 c, привязан к user + bot.

    Недоступный Valkey → 503 у caller'а (handoff без Valkey невозможен).
    """
    code = f"{CODE_PREFIX}{secrets.token_urlsafe(24)}"
    await valkey.get_valkey().set(
        f"miniapp_code:{code}",
        json.dumps({"user_id": user_id, "bot_id": bot_id}, ensure_ascii=False),
        ex=CODE_TTL_SECONDS,
    )
    return code


async def consume_code(code: str) -> dict[str, Any] | None:
    """Одноразовый обмен кода: GETDEL — атомарно (§11). None → код невалид/использован."""
    raw = await valkey.get_valkey().getdel(f"miniapp_code:{code}")
    if raw is None:
        return None
    parsed = json.loads(str(raw))
    return parsed if isinstance(parsed, dict) else None


def generate_mat_token() -> str:
    """mat_<random> — единственный токен, который бэкенд выдаёт сам (§4, §11)."""
    return f"{MAT_PREFIX}{secrets.token_urlsafe(32)}"


def token_hash(token: str) -> str:
    """В Valkey хранится только sha256 токена (§11)."""
    return sha256_hex(token)


async def store_mat_token(*, token: str, user_id: str, bot_id: str) -> None:
    """mat_-токен → Valkey: sha256-хэш → {user_id, bot_id}, TTL 15 мин (§11)."""
    await valkey.get_valkey().set(
        f"miniapp_token:{token_hash(token)}",
        json.dumps({"user_id": user_id, "bot_id": bot_id}, ensure_ascii=False),
        ex=TOKEN_TTL_SECONDS,
    )


async def resolve_mat_token(token: str) -> dict[str, Any] | None:
    """mat_-токен → {user_id, bot_id}; не найден/TTL истёк → None (§11)."""
    with contextlib.suppress(Exception):
        raw = await valkey.get_valkey().get(f"miniapp_token:{token_hash(token)}")
        if raw is None:
            return None
        parsed = json.loads(str(raw))
        if isinstance(parsed, dict):
            return parsed
    return None
