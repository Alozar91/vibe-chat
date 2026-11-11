"""Сообщения: отправка, идемпотентность, цитирование, пересылка, edit/delete, пагинация (§6, §7)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.file import File
from app.models.message import Attachment, Message
from app.models.user import User
from app.services import chats as chat_service
from app.services.files import attachment_url
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Окно редактирования — конфиг через Settings; здесь дефолт на случай прямого вызова
DEFAULT_EDIT_WINDOW_HOURS = 24

_KNOWN_KINDS = {"image", "video", "file"}


def _new_message_id() -> str:
    """UUIDv7 — монотонный, генерирует бэкенд (§6)."""
    import uuid6

    return str(uuid6.uuid7())


def _now() -> datetime:
    return datetime.now(UTC)


def _as_aware(dt: datetime) -> datetime:
    """SQLite отдаёт naive-датетаймы; приводим к UTC для сравнений (PG отдаёт aware)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def validate_timezone(tz_name: str | None) -> str | None:
    """IANA-валидация пояса отправителя; невалидный → NULL (§6)."""
    if not tz_name:
        return None
    try:
        from zoneinfo import available_timezones

        if tz_name in available_timezones():
            return tz_name
    except Exception:
        pass
    return None


async def _validate_reply_target(db: AsyncSession, chat_id: str, reply_to_id: str | None) -> None:
    """Цель цитирования: сообщение того же чата, не system (§7). Удалённое — можно (рендер «удалено»)."""
    if reply_to_id is None:
        return
    target = await db.get(Message, reply_to_id)
    if target is None or target.chat_id != chat_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "reply_to must be in the same chat")
    if target.type == "system":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "cannot reply to system message")


async def _resolve_attachments(
    db: AsyncSession, uploader_id: str, items: list[dict[str, Any]]
) -> list[tuple[Attachment, File]]:
    """Валидация вложений: ready-файл uploader'а, kind сверяется с real_mime_type → 422 (§7)."""
    resolved: list[tuple[Attachment, File]] = []
    for item in items:
        kind = item["kind"]
        if kind not in _KNOWN_KINDS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown attachment kind: {kind}")
        file_row = await db.get(File, item["file_id"])
        if file_row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"file {item['file_id']} not found")
        if file_row.status != "ready":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "file not completed (pending)")
        if file_row.uploader_id != uploader_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "file belongs to another user")
        real = file_row.real_mime_type or file_row.mime_type
        expected = "image" if real.startswith("image/") else "video" if real.startswith("video/") else "file"
        if real == "image/svg+xml":
            expected = "file"  # SVG — не image (§8)
        if kind != expected:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"kind '{kind}' does not match real mime '{real}' (expected '{expected}')",
            )
        attachment = Attachment(
            id=str(uuid.uuid4()),
            file_id=file_row.id,
            kind=kind,
            file_name=item["file_name"],
            width=item.get("width"),
            height=item.get("height"),
            duration_ms=item.get("duration_ms"),
        )
        resolved.append((attachment, file_row))
    return resolved


async def create_message(
    db: AsyncSession,
    *,
    sender: User,
    chat_id: str,
    text: str | None,
    attachments: list[dict[str, Any]],
    reply_to_id: str | None,
    timezone_name: str | None,
    client_ref: str | None,
    edit_window_hours: int = DEFAULT_EDIT_WINDOW_HOURS,
) -> tuple[Message, bool]:
    """Отправка с идемпотентностью (§6): повтор с тем же ключом возвращает созданное сообщение.

    Идемпотентность: UNIQUE (sender_id, client_ref, chat_id); ключ из Idempotency-Key или тела.
    """
    await chat_service.require_member(db, chat_id, sender.id)
    if not text and not attachments:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "text or attachments required")

    if client_ref:
        existing = (
            await db.scalars(
                select(Message).where(
                    Message.sender_id == sender.id,
                    Message.client_ref == client_ref,
                    Message.chat_id == chat_id,
                )
            )
        ).first()
        if existing is not None:
            return existing, False

    await _validate_reply_target(db, chat_id, reply_to_id)
    resolved = await _resolve_attachments(db, sender.id, attachments)
    tz = await validate_timezone(timezone_name)

    message = Message(
        id=_new_message_id(),
        chat_id=chat_id,
        sender_id=sender.id,
        type="text",
        text=text,
        client_ref=client_ref,
        reply_to_id=reply_to_id,
        timezone=tz,
    )
    db.add(message)
    for attachment, _file_row in resolved:
        attachment.message_id = message.id
        db.add(attachment)
    await db.commit()
    await db.refresh(message)
    return message, True


def serialize_message(message: Message, attachments: list[tuple[Attachment, File]]) -> dict[str, Any]:
    """Сериализация с встроенными presigned URL (§8). Soft-deleted — заглушка без вложений."""
    deleted = message.deleted_at is not None
    return {
        "id": message.id,
        "chat_id": message.chat_id,
        "sender_id": message.sender_id,
        "type": message.type,
        "text": message.text if not deleted else None,
        "payload": message.payload,
        "client_ref": message.client_ref,
        "reply_to_id": message.reply_to_id,
        "forward_from_message_id": message.forward_from_message_id,
        "forward_from_chat_id": message.forward_from_chat_id,
        "forward_snapshot": message.forward_snapshot,
        "created_at": message.created_at.isoformat(),
        "updated_at": message.updated_at.isoformat(),
        "timezone": message.timezone,
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
        "deleted_at": message.deleted_at.isoformat() if message.deleted_at else None,
        "attachments": []
        if deleted
        else [
            {
                "id": a.id,
                "file_id": a.file_id,
                "kind": a.kind,
                "file_name": a.file_name,
                "width": a.width,
                "height": a.height,
                "duration_ms": a.duration_ms,
                "url": attachment_url(f, a.file_name),
                "thumb_url": attachment_url(f, a.file_name, thumb=True) if a.kind == "image" else None,
            }
            for a, f in attachments
        ],
    }


async def load_attachments(db: AsyncSession, message_ids: list[str]) -> dict[str, list[tuple[Attachment, File]]]:
    """Вложения + файлы для сообщений одним запросом (N+1 без этого был бы неизбежен)."""
    if not message_ids:
        return {}
    stmt = (
        select(Attachment, File)
        .join(File, File.id == Attachment.file_id)
        .where(Attachment.message_id.in_(message_ids))
    )
    rows = (await db.execute(stmt)).all()
    result: dict[str, list[tuple[Attachment, File]]] = {}
    for attachment, file_row in rows:
        result.setdefault(attachment.message_id, []).append((attachment, file_row))
    return result


async def get_message_checked(db: AsyncSession, message_id: str) -> Message:
    message = await db.get(Message, message_id)
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "message not found")
    return message


async def _require_member_by_message(db: AsyncSession, message: Message, user_id: str) -> None:
    await chat_service.require_member(db, message.chat_id, user_id)


async def edit_message(
    db: AsyncSession,
    *,
    message_id: str,
    actor: User,
    new_text: str,
    edit_window_hours: int = DEFAULT_EDIT_WINDOW_HOURS,
) -> Message:
    """Только автор, только text, только без attachments, окно — конфиг (§6). Ботам нельзя (§10)."""
    message = await get_message_checked(db, message_id)
    await _require_member_by_message(db, message, actor.id)
    if message.sender_id != actor.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only author can edit")
    if actor.is_bot:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bots cannot edit messages")
    if message.deleted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "message deleted")
    has_attachments = (
        await db.scalars(select(Attachment.id).where(Attachment.message_id == message.id))
    ).first()
    if has_attachments is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "messages with attachments cannot be edited")
    if message.edited_at is not None and _as_aware(message.edited_at) < _now() - timedelta(
        hours=edit_window_hours
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "edit window expired")
    if _as_aware(message.created_at) < _now() - timedelta(hours=edit_window_hours):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "edit window expired")
    message.text = new_text
    message.edited_at = _now()
    message.updated_at = _now()
    await db.commit()
    await db.refresh(message)
    return message


async def delete_message(db: AsyncSession, *, message_id: str, actor: User) -> Message:
    """Soft delete: автор — свой; чат-админ — чужие (§12)."""
    message = await get_message_checked(db, message_id)
    await _require_member_by_message(db, message, actor.id)
    if message.deleted_at is not None:
        return message  # идемпотентно
    if message.sender_id != actor.id:
        member = await chat_service.get_member(db, message.chat_id, actor.id)
        if member is None or member.role not in ("owner", "admin"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "author or chat admin required")
    message.deleted_at = _now()
    message.updated_at = _now()
    await db.commit()
    await db.refresh(message)
    return message


def _forward_snapshot(message: Message, sender: User | None) -> dict[str, Any]:
    """Денормализованный снапшот автора/времени — переживает удаление источника (§7)."""
    return {
        "author_user_id": sender.id if sender else None,
        "author_display_name": sender.display_name if sender else None,
        "created_at": message.created_at.isoformat(),
        "timezone": message.timezone,
    }


async def forward_message(
    db: AsyncSession,
    *,
    message_id: str,
    actor: User,
    chat_ids: list[str],
    client_ref: str | None,
) -> list[Message]:
    """Пересылка: атомарно во все чаты, копии вложений (тот же storage_key) (§7).

    Идемпотентность: один ключ на всю операцию; повтор возвращает копии первого запуска.
    """
    source = await get_message_checked(db, message_id)
    await chat_service.require_member(db, source.chat_id, actor.id)  # источник — чат, где состою (§7)

    target_ids = list(dict.fromkeys(chat_ids))
    if source.chat_id in target_ids:
        # пересылка в исходный чат допустима, но дубль-ключ не создаём: фильтруется ниже
        pass

    # идемпотентность forward: ключ + actor → ищем копии предыдущего запуска
    if client_ref:
        existing = (
            await db.scalars(
                select(Message).where(
                    Message.sender_id == actor.id,
                    Message.client_ref == client_ref,
                    Message.chat_id.in_(target_ids),
                )
            )
        ).all()
        if existing and len(existing) >= len(target_ids):
            return list(existing)

    # pre-flight валидация всех чатов: атомарность — 422/403 без частичного эффекта (§7)
    target_list: list[str] = []
    source_sender: User | None = None
    if source.sender_id is not None:
        source_sender = await db.get(User, source.sender_id)
    for chat_id in target_ids:
        await chat_service.require_member(db, chat_id, actor.id)
        target_list.append(chat_id)

    snapshot = _forward_snapshot(source, source_sender)
    source_attachments = await load_attachments(db, [source.id])
    created: list[Message] = []
    for chat_id in target_ids:
        copy = Message(
            id=_new_message_id(),
            chat_id=chat_id,
            sender_id=actor.id,
            type=source.type if source.type == "text" else "text",
            text=source.text,
            client_ref=client_ref,
            forward_from_message_id=source.id,
            forward_from_chat_id=source.chat_id,
            forward_snapshot=snapshot,
            timezone=await validate_timezone(actor.timezone),
        )
        db.add(copy)
        for attachment, file_row in source_attachments.get(source.id, []):
            db.add(
                Attachment(
                    id=str(uuid.uuid4()),
                    message_id=copy.id,
                    file_id=file_row.id,
                    kind=attachment.kind,
                    file_name=attachment.file_name,
                    width=attachment.width,
                    height=attachment.height,
                    duration_ms=attachment.duration_ms,
                )
            )
        created.append(copy)
    await db.commit()
    for copy in created:
        await db.refresh(copy)
    return created


async def list_messages(
    db: AsyncSession,
    *,
    chat_id: str,
    user_id: str,
    before: str | None = None,
    after: str | None = None,
    updated_after: datetime | None = None,
    around: str | None = None,
    limit: int = 50,
) -> list[Message]:
    """Keyset-пагинация по (chat_id, id) — главный индекс (§6).

    after → новые (ASC, для реконнекта); before → лента назад (DESC);
    around → окно вокруг цитаты; updated_after → edit/delete-дельта (§9).
    """
    await chat_service.require_member(db, chat_id, user_id)
    limit = min(max(limit, 1), 100)

    if around is not None:
        anchor = await db.get(Message, around)
        if anchor is None or anchor.chat_id != chat_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "anchor message not found")
        half = limit // 2
        older = (
            await db.scalars(
                select(Message)
                .where(Message.chat_id == chat_id, Message.id <= anchor.id)
                .order_by(Message.id.desc())
                .limit(half + 1)
            )
        ).all()
        newer = (
            await db.scalars(
                select(Message)
                .where(Message.chat_id == chat_id, Message.id > anchor.id)
                .order_by(Message.id.asc())
                .limit(limit - half)
            )
        ).all()
        result = list(reversed(list(older))) + list(newer)
        # старших могло не хватить (начало чата) — добираем более новыми до лимита
        if len(result) < limit:
            extra = (
                await db.scalars(
                    select(Message)
                    .where(Message.chat_id == chat_id, Message.id > anchor.id)
                    .order_by(Message.id.asc())
                    .offset(len(newer))
                    .limit(limit - len(result))
                )
            ).all()
            result = result + list(extra)
        return result[-limit:]

    if after is not None:
        stmt = (
            select(Message)
            .where(Message.chat_id == chat_id, Message.id > after)
            .order_by(Message.id.asc())
            .limit(limit)
        )
        return list((await db.scalars(stmt)).all())

    if updated_after is not None:
        stmt = (
            select(Message)
            .where(
                Message.chat_id == chat_id,
                func.coalesce(Message.edited_at, Message.deleted_at, Message.updated_at)
                > updated_after,
            )
            .order_by(Message.updated_at.asc())
            .limit(limit)
        )
        return list((await db.scalars(stmt)).all())

    stmt = (
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.id.desc())
        .limit(limit)
    )
    if before is not None:
        stmt = (
            select(Message)
            .where(Message.chat_id == chat_id, Message.id < before)
            .order_by(Message.id.desc())
            .limit(limit)
        )
    messages = list((await db.scalars(stmt)).all())
    return list(reversed(messages))  # лента: старые сверху
