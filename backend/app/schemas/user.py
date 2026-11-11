"""API-контракты пользователей."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str
    avatar_file_id: str | None
    is_bot: bool
    is_platform_admin: bool
    time_display: str
    timezone: str | None
    last_seen_at: datetime | None
