"""Звонки: calls, call_participants (Docs/concept.md §6, §17)."""

from datetime import datetime

from app.db.base import Base
from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column


class Call(Base):
    """Звонок в чате; id = имя комнаты LiveKit (§17)."""

    __tablename__ = "calls"
    __table_args__ = (Index("ix_calls_chat_created", "chat_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id"))
    initiator_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(10))  # audio | video (video — этап C)
    status: Mapped[str] = mapped_column(String(10))  # ringing | active | ended
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CallParticipant(Base):
    """Участник звонка: текущее состояние (join/leave), без лога повторных входов (§17)."""

    __tablename__ = "call_participants"

    call_id: Mapped[str] = mapped_column(String(36), ForeignKey("calls.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
