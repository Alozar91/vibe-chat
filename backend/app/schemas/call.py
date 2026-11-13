"""API-контракты звонков (§17)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CallCreateIn(BaseModel):
    chat_id: str
    kind: str = Field(default="audio")  # audio | video


class CallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chat_id: str
    initiator_id: str
    kind: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    participant_ids: list[str] = []


class CallTokenOut(BaseModel):
    token: str
    ws_url: str
