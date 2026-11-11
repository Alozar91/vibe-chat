"""Профили ботов (Docs/concept.md §6, §10): bot_profiles 1:1 users.is_bot."""

from datetime import datetime

from app.db.base import Base
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column


class BotProfile(Base):
    __tablename__ = "bot_profiles"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64))  # только sha256 (§10)
    miniapp_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    miniapp_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(String(512), nullable=True)  # post-MVP
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
