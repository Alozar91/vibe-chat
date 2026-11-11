"""API-контракты ботов (§10, §12)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BotCreateIn(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class BotUpdateIn(BaseModel):
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    miniapp_url: str | None = Field(default=None, max_length=512)
    miniapp_name: str | None = Field(default=None, max_length=255)


class BotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str
    description: str | None
    is_active: bool
    miniapp_url: str | None
    miniapp_name: str | None
    created_at: datetime


class BotCreatedOut(BotOut):
    token: str  # vbt_... — один раз, при создании/регенерации (§10)


class BotAttachmentIn(BaseModel):
    file_id: str
    kind: str
    file_name: str = Field(min_length=1, max_length=255)
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None


class BotMessageIn(BaseModel):
    """POST /bot/messages: текст и/или вложения; reply; идемпотентность (§10)."""

    chat_id: str
    text: str | None = Field(default=None, max_length=40000)
    reply_to_id: str | None = None
    client_ref: str | None = None
    timezone: str | None = Field(default=None, max_length=64)
    attachments: list[BotAttachmentIn] = []


class BotUpdatesOut(BaseModel):
    """GET /bot/updates: события Stream или resync-флаг (§10)."""

    updates: list[dict[str, Any]]
    offset: str | None
    resync: bool = False
