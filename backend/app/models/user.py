"""Модель пользователя (Docs/concept.md §6)."""

from datetime import datetime

from app.db.base import Base
from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    keycloak_sub: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    avatar_file_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    time_display: Mapped[str] = mapped_column(String(20), default="browser", server_default="browser")
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
