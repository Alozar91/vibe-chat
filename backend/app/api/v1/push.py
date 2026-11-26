"""Пуши: роуты device-токенов + версия клиента (Docs/android.md §3.8, этапы 6 и 8).

- POST /push/tokens — регистрация FCM-токена (upsert)
- DELETE /push/tokens/{token} — отвязка (выход из аккаунта)
- GET /app/version — без аутентификации (единственное мобильное исключение
  из «никаких мобильных эндпоинтов», §3.8): {min_version, latest_version}
"""

from typing import Annotated

from app.api.deps import UserDep
from app.core.config import get_settings
from app.db.session import get_db
from app.services import push as push_service
from app.services.server_info import require_join_code
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["push"])
DbDep = Annotated[AsyncSession, Depends(get_db)]


class PushTokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=16, max_length=255)
    platform: str = Field(default="android", pattern="^(android|ios)$")


@router.post("/push/tokens", status_code=201)
async def register_token(body: PushTokenIn, me: UserDep, db: DbDep) -> dict[str, str]:
    """Регистрация FCM-токена устройства (upsert по токену; ротация не плодит строк)."""
    await push_service.register_token(db, user_id=me.id, token=body.token, platform=body.platform)
    return {"status": "registered"}


@router.delete("/push/tokens/{token}", status_code=204)
async def unregister_token(token: str, me: UserDep, db: DbDep) -> None:
    """Отвязка токена (выход из аккаунта). Чужой/несуществующий токен — 404."""
    if not await push_service.unregister_token(db, token=token):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "token not found")


version_router = APIRouter(tags=["app"])


class AppVersionOut(BaseModel):
    min_version: str
    latest_version: str


@version_router.get("/app/version", response_model=AppVersionOut, dependencies=[Depends(require_join_code)])
async def app_version() -> AppVersionOut:
    """Без аутентификации (§3.8): клиент сравнивает свою версию при старте."""
    s = get_settings()
    return AppVersionOut(min_version=s.min_app_version, latest_version=s.latest_app_version)
