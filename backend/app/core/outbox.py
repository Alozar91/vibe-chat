import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OutboxEvent


async def add_event(
    session: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: str | uuid.UUID,
    event_type: str,
    chat_id: uuid.UUID | None = None,
    payload: dict[str, Any],
) -> None:
    session.add(
        OutboxEvent(
            aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id),
            event_type=event_type,
            chat_id=chat_id,
            payload=payload,
        )
    )
