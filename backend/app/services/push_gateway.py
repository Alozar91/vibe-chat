"""FCM-шлюз пушей (Docs/android.md §3.8, этап 6).

Драйверы:
- `console` (dev/эмуляция) — пуш печатается в лог и кладётся в Valkey Stream
  `push:log` (dev-инструменты могут читать), доставка не имитируется дальше;
- `fcm` — Firebase Cloud Messaging HTTP v1 (SA-ключ из APP_FCM_CREDENTIALS_FILE).

Транспорт однотипный: send(tokens, data) → список
мёртвых токенов (UNREGISTERED/INVALID_ARGUMENT → удаляются владельцем).

Payload — только data (§18: контент сообщения в FCM-шине не светится;
title/body строит клиент). notification-часть не отправляется: она
рисует системное уведомление, не поднимая headless JS, — а нам нужен
клиентский рендер (агрегация, имя чата из кэша, deep link).

Зависимости: pyjwt[crypto] (RSA-подпись JWT) + httpx — уже в pyproject;
`google-auth` не нужен.

Триггер — только новые сообщения (§3.5): typing/presence/реакции не пушатся.
"""

import json
import logging
import time

import httpx
import jwt
from app.core.config import get_settings

logger = logging.getLogger("vibe.push")

_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
_FCM_SEND_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"

# Мёртвые токены: FCM отвечает 404 NOT_FOUND / 410 UNREGISTERED / 400 INVALID_ARGUMENT
# на регистрационные токены, отозванные или превышающие лимиты (§3.8 — авто-очистка).
_DEAD_TOKEN_CODES: set[int] = {400, 404, 410}

_access_token: str | None = None
_access_token_exp: float = 0.0


def push_enabled() -> bool:
    """Пуши включены, если задан драйвер и для fcm — файл SA-ключа."""
    s = get_settings()
    if s.push_driver == "console":
        return True
    return bool(s.fcm_credentials_file)


async def send(tokens: list[str], *, data: dict[str, str]) -> list[str]:
    """Отправка пуша на токены. Возвращает мёртвые токены (вызывающий удаляет их)."""
    if not tokens:
        return []
    if get_settings().push_driver == "fcm":
        return await _send_fcm(tokens, data=data)
    return _log_push(tokens, data=data)


# --- console-драйвер (эмуляция) ---


def _log_push(tokens: list[str], *, data: dict[str, str]) -> list[str]:
    for token in tokens:
        logger.info(
            "PUSH (console) token=%s… data=%s",
            token[:8],
            json.dumps(data, ensure_ascii=False),
        )
    return []  # эмуляция не имитирует отзыв токенов


# --- FCM HTTP v1 ---


async def _get_access_token() -> str:
    """JWT (RS256) → OAuth2 access token, кэш до exp-60."""
    global _access_token, _access_token_exp
    if _access_token and time.time() < _access_token_exp - 60:
        return _access_token

    s = get_settings()
    now = int(time.time())
    with open(s.fcm_credentials_file) as f:
        creds = json.load(f)
    assertion = jwt.encode(
        {
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/firebase.messaging",
            "aud": _OAUTH_TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        },
        creds["private_key"],
        algorithm="RS256",
    )
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            _OAUTH_TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        resp.raise_for_status()
        out = resp.json()
    _access_token = out["access_token"]
    _access_token_exp = now + int(out.get("expires_in", 3600))
    return _access_token


async def _send_fcm(tokens: list[str], *, data: dict[str, str]) -> list[str]:
    """Отправка каждого токена отдельным запросом (агрегация уже сделана вызывающим).

    Data-only + priority=high: notification-часть не отправляем — она рисует
    системное уведомление без headless JS (клиент сам строит текст и deep link).
    Ошибки сети/квот — не фатальны (пуш не критичен; повтор — при следующем сообщении).
    """
    s = get_settings()
    token = await _get_access_token()
    url = _FCM_SEND_URL.format(project=s.fcm_project_id)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    dead: list[str] = []
    async with httpx.AsyncClient(timeout=15) as client:
        for reg_token in tokens:
            payload = {
                "message": {
                    "token": reg_token,
                    "data": data,
                    "android": {"priority": "high"},
                }
            }
            try:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code in _DEAD_TOKEN_CODES:
                    dead.append(reg_token)
                elif resp.status_code >= 400:
                    logger.warning("FCM send %d: %s", resp.status_code, resp.text[:200])
            except httpx.HTTPError as e:
                logger.warning("FCM send failed: %s", e)
    return dead
