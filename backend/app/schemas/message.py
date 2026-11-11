"""API-контракты сообщений и файлов (§12)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

TIMEZONE_MAX = 64


class AttachmentIn(BaseModel):
    """Вложение при отправке: file_id должен быть ready-файлом uploader'а (§8)."""

    file_id: str
    kind: str  # image | video | file — сверяется с files.real_mime_type (§7)
    file_name: str = Field(min_length=1, max_length=255)
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None


class MessageCreateIn(BaseModel):
    """POST /chats/{id}/messages — text и/или attachments; forward-поля не принимаются (§7)."""

    text: str | None = None
    attachments: list[AttachmentIn] = []
    reply_to_id: str | None = None
    timezone: str | None = Field(default=None, max_length=TIMEZONE_MAX)

    @field_validator("text")
    @classmethod
    def text_or_attachments(cls, v: str | None, info: Any) -> str | None:
        # непустой текст не требуется, если есть вложения; проверка «хотя бы что-то» — в сервисе
        if v is not None and len(v) > 40000:
            raise ValueError("text too long")
        return v


class MessageEditIn(BaseModel):
    """PATCH /messages/{id} — только text (§6 «Редактирование сообщений»)."""

    text: str = Field(min_length=1, max_length=40000)


class ForwardIn(BaseModel):
    chat_ids: list[str] = Field(min_length=1)


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_id: str
    kind: str
    file_name: str
    width: int | None
    height: int | None
    duration_ms: int | None
    # presigned GET URL встраиваются в сериализацию (§8)
    url: str
    thumb_url: str | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chat_id: str
    sender_id: str | None  # NULL у system
    type: str
    text: str | None
    payload: dict[str, Any] | None
    client_ref: str | None
    reply_to_id: str | None
    forward_from_message_id: str | None
    forward_from_chat_id: str | None
    forward_snapshot: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    timezone: str | None
    edited_at: datetime | None
    deleted_at: datetime | None
    attachments: list[AttachmentOut]


class UploadUrlIn(BaseModel):
    """POST /files/upload-url {size, mime, sha256} (§8)."""

    size: int = Field(gt=0)
    mime: str = Field(min_length=3, max_length=255)
    sha256: str = Field(min_length=64, max_length=64)


class UploadUrlOut(BaseModel):
    file_id: str
    upload_url: str  # presigned PUT
    expires_in: int  # TTL сек


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    size_bytes: int
    mime_type: str
    real_mime_type: str | None
    thumb_key: str | None
    blurhash: str | None
    sha256: str
    created_at: datetime


class FileUrlOut(BaseModel):
    url: str
    expires_in: int
