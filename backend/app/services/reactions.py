"""Реакции на сообщения (Docs/concept.md §6, §12).

Toggle-модель: PUT ставит реакцию пользователя (одна на сообщение — составной
PK), повторный PUT с тем же emoji снимает, с другим — заменяет. Событие
reaction.updated — всему чату. Реакции не двигают messages.updated_at (§6).
"""

from typing import Any

from app.models.message import Message
from app.models.reaction import Reaction
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

ALLOWED_EMOJI = frozenset({"thumbs_up", "heart", "laugh", "fire", "check"})


async def set_reaction(db: AsyncSession, *, message_id: str, user_id: str, emoji: str) -> dict[str, Any]:
    """Toggle реакции (§6): поставить / заменить / снять. Возвращает актуальный список реакций сообщения.

    Только text-сообщения (не system, не удалённые); только участник чата.
    """
    if emoji not in ALLOWED_EMOJI:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"emoji must be one of {sorted(ALLOWED_EMOJI)}")

    message = await db.get(Message, message_id)
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "message not found")
    if message.type != "text" or message.deleted_at is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "cannot react to this message")

    from app.services.chats import require_member

    await require_member(db, message.chat_id, user_id)

    existing = await db.get(Reaction, (message_id, user_id))
    if existing is not None and existing.emoji == emoji:
        await db.delete(existing)  # toggle: та же реакция — снимаем (§6)
    elif existing is not None:
        existing.emoji = emoji  # замена
    else:
        db.add(Reaction(message_id=message_id, user_id=user_id, emoji=emoji))
    await db.commit()

    return await list_reactions(db, [message_id])


async def list_reactions(db: AsyncSession, message_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Реакции сообщений: {message_id: [{emoji, user_ids}]} (§6 — без имён, фронт знает участников)."""
    if not message_ids:
        return {}
    stmt = (
        select(Reaction.message_id, Reaction.emoji, Reaction.user_id)
        .where(Reaction.message_id.in_(message_ids))
        .order_by(Reaction.created_at, Reaction.user_id)
    )
    grouped: dict[tuple[str, str], list[str]] = {}
    for mid, emoji, uid in (await db.execute(stmt)).all():
        grouped.setdefault((mid, emoji), []).append(uid)

    result: dict[str, list[dict[str, Any]]] = {mid: [] for mid in message_ids}
    for (mid, emoji), user_ids in grouped.items():
        result[mid].append({"emoji": emoji, "user_ids": user_ids})
    return result


async def count_reactions(db: AsyncSession, message_ids: list[str]) -> int:
    """Вспомогательное: сколько реакций у сообщений (для тестов)."""
    if not message_ids:
        return 0
    stmt = select(func.count()).select_from(Reaction).where(Reaction.message_id.in_(message_ids))
    return int(await db.scalar(stmt) or 0)


async def delete_all_for_message(db: AsyncSession, message_id: str) -> None:
    """Служебное: снять все реакции сообщения (в MVP не вызывается — надгробие скрывает их)."""
    await db.execute(delete(Reaction).where(Reaction.message_id == message_id))
