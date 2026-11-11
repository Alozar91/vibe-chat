"""Инвайт-коды регистрации (Docs/concept.md §5): invites, multi-use."""

from datetime import datetime

from app.db.base import Base
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column


class Invite(Base):
    """Multi-use инвайт-код: max_uses NULL = безлимит; в БД только sha256-хэш."""

    __tablename__ = "invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)  # NULL = безлимит
    uses_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
