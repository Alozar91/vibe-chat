"""Реакции на сообщения (Docs/concept.md §6): reactions, составной PK."""

from datetime import datetime

from app.db.base import Base
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column


class Reaction(Base):
    """Одна реакция пользователя на сообщение: PK (message_id, user_id) — одна на пользователя."""

    __tablename__ = "reactions"

    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    emoji: Mapped[str] = mapped_column(String(32))  # короткое имя из фиксированного набора (§6)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
