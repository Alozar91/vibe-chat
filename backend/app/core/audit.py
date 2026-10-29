import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import utcnow
from app.models import AuditLog


async def log_action(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            metadata_=metadata or {},
            ip=ip,
            created_at=utcnow(),
        )
    )
