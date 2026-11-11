"""Сообщения: messages, attachments (§6)."""

from datetime import datetime
from typing import Any

from app.db.base import Base
from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_chat_id_id", "chat_id", "id"),)

    # UUIDv7 генерирует бэкенд при вставке — курсор пагинации и порядок (§6)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id"), nullable=False)
    sender_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(10))  # text | system (медиа — только в attachments.kind, §7)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # параметры system-сообщений
    client_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)  # идемпотентность (UNIQUE ниже)
    reply_to_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("messages.id"), nullable=True)
    forward_from_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    forward_from_chat_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    forward_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # автор/время источника
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)  # IANA-пояс отправителя
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.id"), nullable=False)
    file_id: Mapped[str] = mapped_column(String(36), ForeignKey("files.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10))  # image | video | file — источник правды о медиа-типе (§7)
    file_name: Mapped[str] = mapped_column(String(255))
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
