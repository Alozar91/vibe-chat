"""Пуш-сервис (Docs/android.md §3.8, этап 6): регистрация токенов, fanout-агрегация, чистка.

Триггер — только новые сообщения (§3.5). Пуш уходит устройству пользователя,
у которого 0 активных WS-соединений (presence-счётчик Valkey) — иначе
сообщение уже доставлено realtime'ом. Агрегация: контрольная точка
`last_pushed_message_id` на токен; count = сообщения чата после неё и после
курсора прочтения участника. Payload содержит контент (решение 2026-11-25):
title чата, готовый body («от кого и что» либо «N новых сообщений»)
и до 5 последних сообщений строками (InboxStyle) — в headless JS клиенту
неоткуда взять текст.

Драйвер транспорта — push_gateway (console-эмуляция / FCM HTTP v1).
"""

import json
import logging
from datetime import UTC, datetime

from app.core import valkey
from app.models.chat import Chat
from app.models.device_token import DeviceToken
from app.models.message import Message
from app.models.user import User
from app.services import push_gateway
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("vibe.push")

# До скольких последних сообщений включаем в payload для InboxStyle (при count>1)
MAX_PUSH_LINES = 5
_TEXT_LIMIT = 120


async def register_token(db: AsyncSession, *, user_id: str, token: str, platform: str) -> None:
    """POST /push/tokens: upsert по токену (ротация не плодит строк; токен мог
    «перейти» на другой аккаунт после relogin — привязка обновляется)."""
    existing = await db.get(DeviceToken, token)
    if existing is not None:
        existing.user_id = user_id
        existing.platform = platform
        existing.last_seen_at = datetime.now(UTC)
    else:
        db.add(DeviceToken(token=token, user_id=user_id, platform=platform))
    await db.commit()


async def unregister_token(db: AsyncSession, *, token: str) -> bool:
    """DELETE /push/tokens/{token}: отвязка (выход из аккаунта). False — не было."""
    exists = await db.get(DeviceToken, token)
    if exists is None:
        return False
    await db.delete(exists)
    await db.commit()
    return True


async def cleanup_dead_tokens(dead_tokens: list[str]) -> None:
    """UNREGISTERED/INVALID_ARGUMENT от FCM → токен удаляется (§3.8, авто-очистка)."""
    if not dead_tokens:
        return
    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        await db.execute(delete(DeviceToken).where(DeviceToken.token.in_(dead_tokens)))
        await db.commit()
        logger.info("cleaned %d dead push tokens", len(dead_tokens))


async def push_message_to_members(db: AsyncSession, chat_id: str, message: Message) -> None:
    """Fanout нового сообщения на офлайн-устройства участников (§3.5, §3.8).

    Вызывается рядом с WS-фанаутом (publish_message_new). Не тормозит и не
    ломает основной путь отправки: любые ошибки — в лог (пуш не критичен).
    """
    if not push_gateway.push_enabled():
        return
    try:
        member_ids = await _member_ids(db, chat_id)
        for user_id in member_ids:
            if user_id == message.sender_id or await _is_online(user_id):
                continue
            await _push_user(db, user_id=user_id, chat_id=chat_id, message=message)
    except Exception:
        logger.exception("push fanout failed (chat %s)", chat_id)


async def _member_ids(db: AsyncSession, chat_id: str) -> list[str]:
    from app.services.realtime import chat_member_ids

    return await chat_member_ids(db, chat_id)


async def _is_online(user_id: str) -> bool:
    """0 активных WS-соединений → офлайн (presence-счётчик, §9)."""
    remaining = await valkey.get_valkey().get(f"presence:{user_id}")
    return remaining is not None and int(remaining) > 0


async def _push_user(db: AsyncSession, *, user_id: str, chat_id: str, message: Message) -> None:
    """Пуш по всем устройствам пользователя, агрегация — по токенам.

    Контрольная точка per-token: count = сообщения чата после max(cursor, read).
    Системные сообщения не пушатся (§3.5: только новые сообщения от участников).
    """
    if message.type == "system":
        return
    tokens = (
        (await db.execute(select(DeviceToken).where(DeviceToken.user_id == user_id)))
        .scalars()
        .all()
    )
    if not tokens:
        return

    dead: list[str] = []
    for token_row in tokens:
        lower = await _lower_bound(
            db, chat_id=chat_id, user_id=user_id, after_message_id=token_row.last_pushed_message_id
        )
        count = await _count_unpushed(db, chat_id=chat_id, lower=lower)
        if count <= 0:
            continue  # после контрольной точки всё прочитано — пуш не нужен
        data = await _build_payload(db, chat_id=chat_id, message=message, count=count, lower=lower)
        dead.extend(await push_gateway.send([token_row.token], data=data))
        await db.execute(
            update(DeviceToken)
            .where(DeviceToken.token == token_row.token)
            .values(last_pushed_message_id=message.id)
        )
    await db.commit()
    if dead:
        await cleanup_dead_tokens(dead)


async def _lower_bound(
    db: AsyncSession, *, chat_id: str, user_id: str, after_message_id: str | None
) -> str | None:
    """Нижняя граница непрочитанного: max(контрольная точка токена, read-курсор)."""
    from app.models.chat import ChatMember

    lower = after_message_id
    read_cursor = (
        await db.scalar(
            select(ChatMember.last_read_message_id).where(
                ChatMember.chat_id == chat_id, ChatMember.user_id == user_id
            )
        )
    )
    if read_cursor and (lower is None or read_cursor > lower):
        lower = read_cursor
    return lower


async def _count_unpushed(db: AsyncSession, *, chat_id: str, lower: str | None) -> int:
    """Сообщения чата после нижней границы (§3.8 агрегация).

    Прочитанное на другом устройстве не считается (read-курсор участника, §12).
    Само текущее сообщение тоже входит: считаем id > lower; текущее сообщение
    всегда > lower (id — UUIDv7, монотонный).
    """
    conditions = [Message.chat_id == chat_id, Message.type != "system"]
    if lower:
        conditions.append(Message.id > lower)
    stmt = select(Message.id).where(*conditions)
    return len((await db.execute(stmt)).all())


async def _build_payload(
    db: AsyncSession, *, chat_id: str, message: Message, count: int, lower: str | None
) -> dict[str, str]:
    """Payload с контентом (решение 2026-11-25): title чата, готовый body,
    при count>1 — до MAX_PUSH_LINES последних сообщений строками (InboxStyle).

    title: direct — имя собеседника (он же отправитель: получатель всегда
    второй участник), group — title чата. body при одном сообщении — текст
    (в группе с префиксом отправителя); при нескольких — «N новых сообщений».
    """
    chat = await db.get(Chat, chat_id)
    is_group = chat is not None and chat.type == "group"
    sender_name = (
        await db.scalar(select(User.display_name).where(User.id == message.sender_id)) or ""
    )
    title = ((chat.title if chat else None) or "Vibe Chat") if is_group else sender_name

    recent = list(
        (
            await db.execute(
                select(Message.id, Message.sender_id, Message.text)
                .where(
                    Message.chat_id == chat_id,
                    Message.type != "system",
                    *([Message.id > lower] if lower else []),
                )
                .order_by(Message.id.desc())
                .limit(MAX_PUSH_LINES)
            )
        ).all()
    )
    recent.reverse()
    names: dict[str, str] = {}
    if is_group:
        sender_ids = {row.sender_id for row in recent if row.sender_id}
        if sender_ids:
            rows = await db.execute(
                select(User.id, User.display_name).where(User.id.in_(sender_ids))
            )
            names = dict(rows.all())

    def line(sender_id: str | None, text: str | None) -> str:
        t = _clip(text) if (text or "").strip() else "📎 Вложение"
        if is_group:
            name = names.get(sender_id or "", "")
            return f"{name}: {t}" if name else t
        return t

    lines = [line(row.sender_id, row.text) for row in recent]

    if count > 1:
        body = f"{count} {_unread_word(count)}"
        return {
            "chat_id": chat_id,
            "message_id": message.id,
            "count": str(count),
            "title": title,
            "body": body,
            "lines": json.dumps(lines, ensure_ascii=False),
        }
    return {
        "chat_id": chat_id,
        "message_id": message.id,
        "count": "1",
        "title": title,
        "body": line(message.sender_id, message.text),
    }


def _clip(s: str | None, limit: int = _TEXT_LIMIT) -> str:
    s = (s or "").strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _unread_word(n: int) -> str:
    """Русская плюрализация: 1 новое сообщение / 2 новых сообщения / 5 новых сообщений."""
    if n % 10 == 1 and n % 100 != 11:
        return "новое сообщение"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "новых сообщения"
    return "новых сообщений"
