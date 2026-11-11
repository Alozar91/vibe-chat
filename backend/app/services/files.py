"""Файлы: presigned PUT/GET через Silo (S3), complete со sniffing mime и thumbnail (§8).

Загрузка не проксируется: клиент кладёт файл напрямую presigned PUT, бэкенд при
complete делает HEAD-проверку (реальный размер и mime — sniffing), для image —
thumbnail (Pillow) + blurhash. Права: pending видит только uploader; чтение
ready — через membership чата с вложением (проверка в сообщениях/роутах).
"""

import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3  # type: ignore[import-untyped]
from app.core.config import get_settings
from app.models.file import File
from botocore.client import Config as BotoConfig  # type: ignore[import-untyped]
from fastapi import HTTPException, status
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# SVG — не image (может содержать скрипты, §8); thumbnails только для растровых
_IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_THUMB_SIZE = (320, 320)


def _s3_client() -> Any:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.silo_internal_url,
        aws_access_key_id=settings.silo_access_key,
        aws_secret_access_key=settings.silo_secret_key,
        config=BotoConfig(signature_version="s3v4"),
        region_name="us-east-1",
    )


def _public_host() -> str:
    """Host, зашиваемый в presigned URL (входит в подпись, §13)."""
    return get_settings().silo_public_url


def new_file_id() -> str:
    return str(uuid.uuid4())


def new_storage_key(file_id: str) -> str:
    return f"files/{file_id}"


def thumb_storage_key(file_id: str) -> str:
    return f"thumbs/{file_id}"


def presign_put(storage_key: str, size: int, mime: str, ttl_seconds: int) -> str:
    """Presigned PUT на публичном host (входит в подпись, §13): браузер кладёт файл
    напрямую в Silo по публичному адресу — как и читает по presigned GET."""
    client = _s3_client()
    params: dict[str, Any] = {
        "Bucket": get_settings().silo_bucket,
        "Key": storage_key,
        "ContentLength": size,
        "ContentType": mime,
    }
    url: str = client.generate_presigned_url("put_object", Params=params, ExpiresIn=ttl_seconds)
    url = str(url)
    internal = get_settings().silo_internal_url
    public = _public_host()
    if internal != public:
        url = url.replace(internal, public, 1)
    return url


def presign_get_url(storage_key: str, *, ttl_seconds: int, download_name: str | None = None) -> str:
    """Presigned GET; для не-image/video — response-content-disposition: attachment (§8)."""
    params: dict[str, str] = {"Bucket": get_settings().silo_bucket, "Key": storage_key}
    if download_name is not None:
        params["ResponseContentDisposition"] = f'attachment; filename="{download_name}"'
    client = _s3_client()
    # подписываем на публичный host: подменяем endpoint на SILO_PUBLIC_URL,
    # чтобы подпись совпала с тем, по чему ходит клиент (§13)
    internal = get_settings().silo_internal_url
    public = _public_host()
    url = client.generate_presigned_url("get_object", Params=params, ExpiresIn=ttl_seconds)
    url = str(url)
    if internal != public:
        url = url.replace(internal, public, 1)
    return url


def ensure_bucket() -> None:
    """Создаёт бакет, если его нет (§8, вызов при старте бэкенда).

    Идемпотентно: 409 BucketAlreadyOwnedByYou — норма. Недоступный Silo не
    роняет старт: вызывающая сторона (lifespan) глотает исключение.
    """
    client = _s3_client()
    bucket = get_settings().silo_bucket
    try:
        client.head_bucket(Bucket=bucket)
    except client.exceptions.ClientError:
        client.create_bucket(Bucket=bucket)


def head_object(storage_key: str) -> dict[str, Any]:
    """HEAD объекта в Silo; отсутствует — 404 (complete по незагруженному)."""
    client = _s3_client()
    try:
        head: dict[str, Any] = client.head_object(Bucket=get_settings().silo_bucket, Key=storage_key)
        return head
    except client.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "object not found in storage") from exc
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "storage error") from exc


def read_object_prefix(storage_key: str, length: int = 64 * 1024) -> bytes:
    """Первые байты объекта — для mime-sniffing и thumbnail при complete (§8).

    Для изображений до 64 КБ хватает целиком; бо́льшие читаются Pillow по Range
    частично — упрощение MVP: читаем prefix, если изображение больше — thumbnail
    деградирует (None), файл остаётся file-attachment.
    """
    client = _s3_client()
    try:
        response = client.get_object(
            Bucket=get_settings().silo_bucket, Key=storage_key, Range=f"bytes=0-{length - 1}"
        )
        body: bytes = response["Body"].read()
        return body
    except client.exceptions.ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "object not found in storage") from exc
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "storage error") from exc


async def can_read_file(db: AsyncSession, file_row: File, user_id: str) -> bool:
    """Право чтения ready-файла: членство в чате, где файл прикреплён (§8)."""
    from app.models.chat import ChatMember
    from app.models.message import Attachment, Message

    attachment_chats = await db.scalars(
        select(Attachment.message_id).where(Attachment.file_id == file_row.id)
    )
    message_ids = list(attachment_chats.all())
    if not message_ids:
        return False
    chat_stmt = select(Message.chat_id).where(Message.id.in_(message_ids))
    chat_ids = list((await db.scalars(chat_stmt)).all())
    if not chat_ids:
        return False
    member_stmt = select(ChatMember.user_id).where(
        ChatMember.user_id == user_id, ChatMember.chat_id.in_(chat_ids)
    )
    return (await db.scalars(member_stmt)).first() is not None


def sniff_mime(data_prefix: bytes, claimed: str) -> str:
    """Определение реального mime: сначала python-magic-подобный sniffing по сигнатурам MVP.

    Полный magic-сниффер не нужен: клиентские mime почти всегда верны, а важные
    случаи (SVG под видом image, exe под видом image) ловим сигнатурами.
    """
    if data_prefix.startswith(b"<?xml") or data_prefix.lstrip().startswith(b"<svg"):
        return "image/svg+xml"
    if data_prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data_prefix.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data_prefix.startswith(b"GIF8"):
        return "image/gif"
    if data_prefix.startswith(b"RIFF") and data_prefix[8:12] == b"WEBP":
        return "image/webp"
    if data_prefix.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    if data_prefix.startswith(b"PK\x03\x04"):
        return "application/zip"
    if data_prefix.startswith(b"%PDF"):
        return "application/pdf"
    if b"\x00" in data_prefix[:512]:
        return "application/octet-stream"
    return claimed if claimed else "text/plain"


def make_thumbnail_and_blurhash(file_row: File, data: bytes) -> tuple[str, str] | None:
    """Thumbnail (Pillow) + blurhash для image (кроме SVG, §8).

    Данные читаются вызывающим кодом (complete) в память. Возвращает
    (thumb_key, blurhash) или None (не image / битое изображение).
    """
    if file_row.real_mime_type not in _IMAGE_MIMES:
        return None
    import blurhash as blurhash_lib  # type: ignore[import-untyped]
    import numpy as np

    img: Image.Image
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        # битое изображение: файл остаётся file-attachment, не image (безопасный fallback)
        file_row.real_mime_type = "application/octet-stream"
        return None

    rgb = img if img.mode == "RGB" else img.convert("RGB")
    thumb = rgb.copy()
    thumb.thumbnail(_THUMB_SIZE)
    buffer = io.BytesIO()
    thumb.save(buffer, format="JPEG", quality=80)
    key = thumb_storage_key(file_row.id)
    client = _s3_client()
    client.put_object(
        Bucket=get_settings().silo_bucket,
        Key=key,
        Body=buffer.getvalue(),
        ContentType="image/jpeg",
    )
    hashed = blurhash_lib.encode(np.asarray(rgb), 4, 3)
    return key, str(hashed)


async def get_file_checked(db: AsyncSession, file_id: str) -> File:
    file_row = await db.get(File, file_id)
    if file_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
    return file_row


def get_download_url(file_row: File, *, inline_ok: bool) -> str:
    """Presigned GET с disposition по реальному mime (§8): inline только image/video."""
    real = file_row.real_mime_type or file_row.mime_type
    inline = inline_ok and (real.startswith("image/") or real.startswith("video/"))
    if inline:
        return presign_get_url(file_row.storage_key, ttl_seconds=get_settings().presign_ttl_seconds)
    return presign_get_url(
        file_row.storage_key,
        ttl_seconds=get_settings().presign_ttl_seconds,
        download_name="file",
    )


def attachment_url(file_row: File, file_name: str, *, thumb: bool = False) -> str:
    """URL для сериализации вложений: thumb — для image-превью, иначе оригинал."""
    settings = get_settings()
    if thumb and file_row.thumb_key:
        return presign_get_url(file_row.thumb_key, ttl_seconds=settings.presign_ttl_seconds)
    real = file_row.real_mime_type or file_row.mime_type
    inline = real.startswith("image/") or real.startswith("video/")
    return presign_get_url(
        file_row.storage_key,
        ttl_seconds=settings.presign_ttl_seconds,
        download_name=None if inline else file_name,
    )


def utcnow() -> datetime:
    return datetime.now(UTC)


def expires_at(seconds: int) -> datetime:
    return utcnow() + timedelta(seconds=seconds)
