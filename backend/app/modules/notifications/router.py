import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import bad_request, not_found
from app.core.security import AuthContext
from app.db.session import get_session
from app.models import Device
from app.modules.auth.dependencies import get_auth_context, require_csrf

router = APIRouter(prefix="/v1/devices", tags=["devices"], dependencies=[Depends(require_csrf)])


class DeviceRegister(BaseModel):
    model_config = {"extra": "forbid"}

    platform: str
    push_token: str | None = None
    webpush_subscription: dict | None = None
    device_id: str | None = None
    app_version: str | None = None


async def _register(session: AsyncSession, ctx: AuthContext, payload: DeviceRegister) -> dict:
    from app.core.timeutil import utcnow

    if payload.platform not in ("ios", "android", "web"):
        raise bad_request("platform: ios|android|web")
    if payload.platform == "web":
        if not payload.webpush_subscription or not payload.webpush_subscription.get("endpoint"):
            raise bad_request("webpush_subscription.endpoint обязателен")
        push_token = None
        webpush_endpoint = str(payload.webpush_subscription["endpoint"])
        webpush_keys = payload.webpush_subscription.get("keys") or {}
    else:
        if not payload.push_token:
            raise bad_request("push_token обязателен")
        push_token = payload.push_token
        webpush_endpoint = None
        webpush_keys = None
    device = Device(
        user_id=ctx.user_id,
        platform=payload.platform,
        push_token=push_token,
        webpush_endpoint=webpush_endpoint,
        webpush_keys=webpush_keys,
        device_id=payload.device_id,
        app_version=payload.app_version,
        last_seen_at=utcnow(),
    )
    session.add(device)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        stmt = select(Device).where(
            Device.platform == payload.platform,
            (Device.push_token == push_token) if push_token else (Device.webpush_endpoint == webpush_endpoint),
        )
        existing = (await session.scalars(stmt)).one_or_none()
        if existing is None:
            raise
        existing.user_id = ctx.user_id
        existing.last_seen_at = utcnow()
        existing.app_version = payload.app_version
        await session.commit()
        return {"id": str(existing.id)}
    return {"id": str(device.id)}


@router.post("")
async def register_device(
    payload: DeviceRegister,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> dict:
    return await _register(db, ctx, payload)


@router.delete("/{device_id}")
async def delete_device(
    device_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_session),
) -> Response:
    try:
        did = uuid.UUID(device_id)
    except ValueError as exc:
        raise bad_request("device_id: некорректный UUID") from exc
    device = await db.get(Device, did)
    if device is None or device.user_id != ctx.user_id:
        raise not_found("Устройство")
    await db.delete(device)
    await db.commit()
    return Response(status_code=204)
