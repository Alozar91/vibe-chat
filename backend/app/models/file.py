"""Файлы: files (статусы pending/ready, §8)."""

from datetime import datetime

from app.db.base import Base
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column


class File(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(10))  # pending | ready
    bucket: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column()
    mime_type: Mapped[str] = mapped_column(String(255))  # заявленный клиентом
    real_mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)  # sniffing при complete
    thumb_key: Mapped[str | None] = mapped_column(String(512), nullable=True)  # заполняется при complete (image)
    blurhash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # заполняется при complete (image)
    sha256: Mapped[str] = mapped_column(String(64))
    uploader_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
