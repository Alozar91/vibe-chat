"""API-контракты пользователей."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    avatar_file_id: str | None
    is_bot: bool
    is_platform_admin: bool
    time_display: str
    timezone: str | None
    last_seen_at: datetime | None


class UserUpdateIn(BaseModel):
    """PATCH /users/me — персональные данные только на уровне системы (§5).

    Все поля опциональны; None означает «очистить поле» (передавать явно).
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    avatar_file_id: str | None = Field(default=None, max_length=36)
    time_display: str | None = Field(default=None, pattern="^(browser|as_sent|fixed|utc)$")
    timezone: str | None = Field(default=None, max_length=64)
