"""Server selection / self-host (концепция §19): discovery /server/info + фейс-контроль.

- GET /server/info (без аутентификации) — единственный источник правды по адресам
  для клиента: kc_url, realm, пуш-конфиг (§19.6), версии, ссылка на APK.
- Кодовое слово сервера (§19.5): opt-in (APP_JOIN_CODE пуст = выключено).
  Неаутентифицированные эндпоинты требуют заголовок X-Vibe-Join; сверка constant-time,
  rate-limit на неуспешные попытки per-IP (иначе код брутфорсится).
  Границы (§19.5): код не защищает ROPC/PKCE (идут напрямую в Keycloak) —
  это фейс-контроль против энумерации и открытой регистрации, не замена аутентификации.
"""

import json
import logging
import secrets
import threading
import time
from collections import deque
from pathlib import Path

from app.core.config import get_settings
from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

# --- Фейс-контроль (§19.5) -------------------------------------------------

_JOIN_FAILURE_WINDOW = 60.0  # сек
_JOIN_MAX_FAILURES = 10  # неуспешных попыток за окно с одного IP → 429
_failures: dict[str, deque[float]] = {}
_failures_lock = threading.Lock()


def reset_join_rate_limit() -> None:
    """Сброс состояния rate-limit'а (для тестов)."""
    with _failures_lock:
        _failures.clear()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


async def require_join_code(request: Request) -> None:
    """Dependency для неаутентифицированных эндпоинтов (§19.5).

    APP_JOIN_CODE пуст → код не требуется (opt-in). Иначе — X-Vibe-Join;
    неверный/отсутствующий → 403 join_code_required (единая ошибка — без оракула),
    >10 неуспешных за минуту с IP → 429.
    """
    code = get_settings().join_code
    if not code:
        return

    ip = _client_ip(request)
    now = time.monotonic()
    with _failures_lock:
        dq = _failures.get(ip)
        if dq is not None:
            while dq and now - dq[0] > _JOIN_FAILURE_WINDOW:
                dq.popleft()
            if len(dq) >= _JOIN_MAX_FAILURES:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_requests")

    provided = request.headers.get("x-vibe-join", "")
    if not secrets.compare_digest(provided.encode("utf-8"), code.encode("utf-8")):
        with _failures_lock:
            _failures.setdefault(ip, deque()).append(now)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "join_code_required")

    # Верный код — счётчик неуспешных сбрасываем
    with _failures_lock:
        _failures.pop(ip, None)


# --- Discovery-профиль (§19.4) ---------------------------------------------


def parse_firebase_client_config(path: str) -> dict[str, str] | None:
    """google-services.json → поля для рантайм-инициализации Firebase на клиенте (§19.6).

    Выбирается client с package_name == fcm_client_package (хостер регистрирует
    НАШ пакет в СВОЁМ Firebase-проекте — сборка не нужна). Ошибка/нет файла → None
    (клиент тогда использует зашитый дефолт, пуши через сервер просто не заработают
    до починки конфига — не 5xx: discovery должен открываться всегда).
    """
    if not path:
        return None
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        project = raw.get("project_info", {})
        for client in raw.get("client", []):
            info = client.get("client_info", {})
            if (
                info.get("android_client_info", {}).get("package_name")
                == get_settings().fcm_client_package
            ):
                api_key = next(
                    (k.get("current_key", "") for k in client.get("api_key", [])), ""
                )
                return {
                    "project_id": project.get("project_id", ""),
                    "sender_id": project.get("project_number", ""),
                    "storage_bucket": project.get("storage_bucket", ""),
                    "app_id": info.get("mobilesdk_app_id", ""),
                    "api_key": api_key,
                }
    except (OSError, ValueError, AttributeError):
        logger.exception("firebase client config parse failed: %s", path)
        return None
    logger.warning("firebase client config: package %s не найден в %s", get_settings().fcm_client_package, path)
    return None


def build_server_info() -> dict[str, object]:
    """Профиль для GET /server/info (§19.4). min/latest/download — §18/§19.4."""
    s = get_settings()
    firebase = None
    if s.push_driver == "fcm":
        firebase = parse_firebase_client_config(s.firebase_config_path)
    return {
        "name": s.server_name,
        "kc_url": s.public_keycloak_url or s.keycloak_url,
        "realm": s.keycloak_realm,
        "push": {"driver": s.push_driver, "firebase": firebase},
        "min_version": s.min_app_version,
        "latest_version": s.latest_app_version,
        "app_download_url": s.app_download_url,
    }
