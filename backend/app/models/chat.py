"""Чаты: chats, chat_members, direct_chat_keys (Docs/concept.md §6)."""

from datetime import datetime

from app.db.base import Base
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[str] = mapped_column(String(10))  # direct | group
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)  # для group
    avatar_file_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatMember(Base):
    __tablename__ = "chat_members"

    chat_id: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(10))  # owner | admin | member
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_read_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DirectChatKey(Base):
    """Служебная таблица: отсортированная пара user_id → chat_id (§6, защита от дублей direct)."""

    __tablename__ = "direct_chat_keys"
    __table_args__ = (UniqueConstraint("user_a", "user_b", name="uq_direct_pair"),)

    chat_id: Mapped[str] = mapped_column(String(36), ForeignKey("chats.id"), primary_key=True)
    user_a: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    user_b: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
