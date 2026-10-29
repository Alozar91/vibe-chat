import asyncio
import uuid
from typing import Any

import boto3
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import bad_request, forbidden, not_found
from app.models import ChatMember, ChatMemberStatus, File, MessageAttachment, User

ALLOWED_MIME_PREFIXES = (
    "image/",
    "video/",
    "audio/",
    "text/",
    "application/pdf",
    "application/zip",
    "application/x-zip-compressed",
    "application/msword",
    "application/vnd.openxmlformats-officedocument",
    "application/vnd.ms-excel",
    "application/json",
)


def _s3_client():
    settings = get_settings()
    endpoint = settings.s3_endpoint_url
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name="us-east-1",
    )


def _presign_put(key: str, content_type: str) -> str:
    settings = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_for_signing(),
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name="us-east-1",
    )
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=settings.presign_put_ttl,
    )


def endpoint_for_signing() -> str:
    settings = get_settings()
    return settings.s3_public_url or settings.s3_endpoint_url


def _presign_get(key: str) -> str:
    settings = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_for_signing(),
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name="us-east-1",
    )
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=settings.presign_get_ttl,
    )


def _head_object(key: str) -> dict[str, Any] | None:
    client = _s3_client()
    try:
        return client.head_object(Bucket=get_settings().s3_bucket, Key=key)
    except Exception:
        return None


def ensure_bucket() -> None:
    settings = get_settings()
    client = _s3_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except Exception:
        client.create_bucket(Bucket=settings.s3_bucket)


def serialize_file(file: File) -> dict[str, Any]:
    return {
        "id": str(file.id),
        "name": file.name,
        "mime_type": file.mime_type,
        "size_bytes": file.size_bytes,
        "status": "ready",
        "av_status": file.av_status,
        "thumbnail_url": f"/v1/media/{file.id}/url?variant=thumb" if file.thumbnail_key else None,
    }


async def create_upload_intent(
    session: AsyncSession, owner_id: uuid.UUID, name: str, mime_type: str, size_bytes: int
) -> dict[str, Any]:
    settings = get_settings()
    name = (name or "").strip()
    if not name or len(name) > 255 or "/" in name or "\\" in name:
        raise bad_request("name: 1..255 символов, без разделителей пути")
    if not mime_type or not mime_type.startswith(ALLOWED_MIME_PREFIXES):
        raise bad_request("MIME-тип не разрешён")
    if size_bytes < 1 or size_bytes > settings.max_file_size:
        raise too_large_error(settings.max_file_size)
    storage_key = f"files/{uuid.uuid4().hex}/{name}"
    av_status = "pending" if settings.clamav_host else "skip"
    file = File(
        owner_id=owner_id,
        name=name,
        mime_type=mime_type,
        size_bytes=size_bytes,
        sha256=f"pending:{uuid.uuid4().hex}",
        storage_key=storage_key,
        av_status=av_status,
    )
    session.add(file)
    await session.commit()
    upload_url = await asyncio.to_thread(_presign_put, storage_key, mime_type)
    result = serialize_file(file)
    result["file_id"] = result["id"]
    result["upload_url"] = upload_url
    result["method"] = "PUT"
    result["headers"] = {"Content-Type": mime_type}
    result["expires_at"] = None
    result["max_size_bytes"] = settings.max_file_size
    return result


def too_large_error(max_size: int):
    from app.core.errors import too_large

    return too_large(f"Размер файла превышает {max_size // (1024 * 1024)} МБ")


async def complete_upload(session: AsyncSession, owner_id: uuid.UUID, file_id: uuid.UUID) -> dict[str, Any]:
    file = await session.get(File, file_id)
    if file is None or file.owner_id != owner_id:
        raise not_found("Файл")
    head = await asyncio.to_thread(_head_object, file.storage_key)
    if head is None:
        raise bad_request("Файл ещё не загружен в хранилище")
    actual_size = int(head.get("ContentLength", 0))
    if actual_size != file.size_bytes:
        raise bad_request(f"Размер в хранилище ({actual_size}) не совпадает с заявленным ({file.size_bytes})")
    if head.get("ContentType") and file.mime_type != head.get("ContentType"):
        file.mime_type = head["ContentType"]
    return serialize_file(file)


async def file_access_allowed(session: AsyncSession, file: File, viewer_id: uuid.UUID) -> bool:
    if file.owner_id == viewer_id:
        return True
    avatar_owner = (
        await session.scalars(select(User).where(User.avatar_file_id == file.id).limit(1))
    ).one_or_none()
    if avatar_owner is not None:
        return True
    attached = (
        await session.scalars(
            select(MessageAttachment.chat_id)
            .where(MessageAttachment.file_id == file.id)
            .limit(1)
        )
    ).one_or_none()
    if attached is None:
        return False
    member = (
        await session.scalars(
            select(ChatMember)
            .where(
                ChatMember.chat_id == attached,
                ChatMember.user_id == viewer_id,
                ChatMember.status == ChatMemberStatus.ACTIVE,
            )
        )
    ).one_or_none()
    return member is not None


async def get_download_url(session: AsyncSession, file_id: uuid.UUID, viewer_id: uuid.UUID) -> dict[str, Any]:
    file = await session.get(File, file_id)
    if file is None:
        raise not_found("Файл")
    if not await file_access_allowed(session, file, viewer_id):
        raise forbidden("Нет доступа к файлу")
    url = await asyncio.to_thread(_presign_get, file.storage_key)
    return {"url": url, "expires_in": get_settings().presign_get_ttl}
