"""Server selection / self-host (концепция §19): GET /server/info.

Discovery без аутентификации — единственный источник адресов/конфига для клиента
(§19.1); защищён фейс-контролем наравне с /auth/register и /app/version (§19.5).
"""

from typing import Any

from app.services.server_info import build_server_info, require_join_code
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

router = APIRouter(tags=["server"])


class PushInfoOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver: str
    firebase: dict[str, str] | None = None


class ServerInfoOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kc_url: str
    realm: str
    push: PushInfoOut
    min_version: str
    latest_version: str
    app_download_url: str


@router.get("/server/info", response_model=ServerInfoOut, dependencies=[Depends(require_join_code)])
async def server_info() -> dict[str, Any]:
    """Профиль сервера для онбординга клиента (§19.4); фейс-контроль §19.5."""
    return build_server_info()
