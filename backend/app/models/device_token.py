"""Device-токены пушей (Docs/android.md §3.8, этап 6): FCM-токены устройств."""

from datetime import datetime

from app.db.base import Base
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column


class DeviceToken(Base):
    """FCM-токен устройства, привязанный к пользователю (§3.8).

    PK — сам токен (upsert при повторной регистрации). last_pushed_message_id —
    контрольная точка агрегации: сколько сообщений чата накопилось после неё
    (и после last_read участника) — столько и кладём в payload пуша.
    """

    __tablename__ = "device_tokens"

    token: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(20))  # "android"
    last_pushed_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
