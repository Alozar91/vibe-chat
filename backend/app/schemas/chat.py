"""API-контракты чатов."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class ChatMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    role: str
    last_read_message_id: str | None


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    title: str | None
    avatar_file_id: str | None
    created_by: str
    created_at: datetime
    deleted_at: datetime | None


class ChatDetailOut(ChatOut):
    members: list[ChatMemberOut]


class ChatCreateIn(BaseModel):
    # Групповой: {title, member_ids[]} (member_ids >= 1, creator игнорируется, боты допустимы — §12)
    title: str
    member_ids: list[str]

    @field_validator("member_ids")
    @classmethod
    def at_least_one(cls, v: list[str]) -> list[str]:
        if len(v) < 1:
            raise ValueError("member_ids must contain at least 1 user")
        return v


class DirectCreateIn(BaseModel):
    user_id: str


class DirectCreatedOut(BaseModel):
    chat_id: str
    created: bool  # true — новый чат, false — вернули существующий


class ReadIn(BaseModel):
    """POST /chats/{id}/read — {message_id} этого чата (§12)."""

    message_id: str
