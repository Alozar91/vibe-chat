"""Инвайт-регистрация: роуты (Docs/concept.md §5, §12).

POST /auth/register — публичный (без аутентификации); /invites/* —
платформенный админ.
"""

from datetime import datetime
from typing import Annotated, Any

from app.api.deps import UserDep
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.user import UserOut
from app.services import invites as invite_service
from app.services.keycloak_admin import get_kc_admin
from app.services.server_info import require_join_code
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["auth"])
admin_router = APIRouter(tags=["invites"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


class RegisterIn(BaseModel):
    """POST /auth/register: инвайт-код + credentials + персональные данные (§5).

    Персональные данные опциональны (можно дозаполнить через PATCH /users/me).
    """

    model_config = ConfigDict(extra="forbid")

    # опционален (§5): None/"" — открытая регистрация (APP_OPEN_REGISTRATION=true),
    # иначе 422; переданный код проверяется и потребляется как обычно
    invite_code: str | None = Field(default=None, max_length=256)
    username: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)


class InviteCreateIn(BaseModel):
    """POST /invites: multi-use код (max_uses NULL = безлимит) с опциональным сроком."""

    model_config = ConfigDict(extra="forbid")

    max_uses: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None


class InviteOut(BaseModel):
    id: str
    max_uses: int | None
    uses_count: int
    expires_at: datetime | None
    deactivated_at: datetime | None
    created_at: datetime


class InviteCreatedOut(InviteOut):
    code: str  # показывается один раз при создании (§5)


@router.post("/auth/register", response_model=UserOut, status_code=201, dependencies=[Depends(require_join_code)])
async def register(body: RegisterIn, db: DbDep) -> UserOut:
    """Регистрация (§5): KC-аккаунт (username+password) + пользователь системы.

    Персональные данные — только в PostgreSQL; Keycloak персональных данных не
    получает. Не настроен Admin API → 503; код невалиден → 404/410; кода нет и
    открытая регистрация выключена → 422; username занят → 409; Keycloak
    недоступен → 502.
    """
    user = await invite_service.register(
        db,
        invite_code=body.invite_code,
        open_registration=get_settings().open_registration,
        username=body.username,
        password=body.password,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        display_name=body.display_name,
        kc_admin=get_kc_admin(),
    )
    return UserOut.model_validate(user)


@admin_router.post("/invites", response_model=InviteCreatedOut, status_code=201)
async def create_invite(body: InviteCreateIn, me: UserDep, db: DbDep) -> InviteCreatedOut:
    """Создать multi-use инвайт-код (платформенный админ, §5); код — один раз в ответе."""
    invite, code = await invite_service.create_invite(
        db, admin=me, max_uses=body.max_uses, expires_at=body.expires_at
    )
    return InviteCreatedOut(**invite_out_dict(invite), code=code)


@admin_router.get("/invites", response_model=list[InviteOut])
async def list_invites(me: UserDep, db: DbDep) -> list[dict[str, Any]]:
    return await invite_service.list_invites(db, admin=me)


@admin_router.post("/invites/{invite_id}/deactivate", response_model=InviteOut)
async def deactivate_invite(invite_id: str, me: UserDep, db: DbDep) -> dict[str, Any]:
    """Деактивировать код: новые регистрации по нему сразу 410 (§5)."""
    return await invite_service.deactivate_invite(db, admin=me, invite_id=invite_id)


def invite_out_dict(invite: Any) -> dict[str, Any]:
    """Invite → dict для InviteCreatedOut (поля уже ISO-строки/типы InviteOut)."""
    return {
        "id": invite.id,
        "max_uses": invite.max_uses,
        "uses_count": invite.uses_count,
        "expires_at": invite.expires_at,
        "deactivated_at": invite.deactivated_at,
        "created_at": invite.created_at,
    }
