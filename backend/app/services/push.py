"""Пуш-сервис (Docs/android.md §3.8, этап 6): регистрация токенов, fanout-агрегация, чистка.

Триггер — только новые сообщения (§3.5). Пуш уходит устройству пользователя,
у которого 0 активных WS-соединений (presence-счётчик Valkey) — иначе
сообщение уже доставлено realtime'ом. Агрегация: контрольная точка
`last_pushed_message_id` на токен; count = сообщения чата после неё и после
курсора прочтения участника. Payload — только идентификаторы (§3.8), текст
клиент подтягивает сам через REST.

Драйвер транспорта — push_gateway (console-эмуляция / FCM HTTP v1).
"""

import logging
from datetime import UTC, datetime

from app.core import valkey
from app.models.device_token import DeviceToken
from app.models.message import Message
from app.services import push_gateway
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("vibe.push")


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

    body = _body_of(message)
    title = await _chat_title(db, chat_id)
    dead: list[str] = []
    for token_row in tokens:
        count = await _count_unpushed(
            db, chat_id=chat_id, user_id=user_id, after_message_id=token_row.last_pushed_message_id
        )
        if count <= 0:
            continue  # после контрольной точки всё прочитано — пуш не нужен
        data = {"chat_id": chat_id, "message_id": message.id, "count": str(count)}
        dead.extend(await push_gateway.send([token_row.token], title=title, body=body, data=data))
        await db.execute(
            update(DeviceToken)
            .where(DeviceToken.token == token_row.token)
            .values(last_pushed_message_id=message.id)
        )
    await db.commit()
    if dead:
        await cleanup_dead_tokens(dead)


def _body_of(message: Message) -> str:
    """Тело пуша: текст сообщения или текст системного события; обрезка 120."""
    from app.services.messages import SYSTEM_TEXTS

    display = message.text or SYSTEM_TEXTS.get((message.payload or {}).get("kind", ""), "новое сообщение")
    return display if len(display) <= 120 else display[:117] + "…"


async def _count_unpushed(
    db: AsyncSession, *, chat_id: str, user_id: str, after_message_id: str | None
) -> int:
    """Сообщения чата после max(контрольной точки токена, курсора прочтения).

    Прочитанное на другом устройстве не считается (read-курсор участника, §12).
    Само текущее сообщение тоже входит: считаем id > after, потом сравним
    read-курсор; текущее сообщение всегда > after (id — UUIDv7, монотонный).
    """
    from app.models.chat import ChatMember

    # нижняя граница: max(контрольная точка токена, read-курсор участника)
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
    conditions = [Message.chat_id == chat_id, Message.type != "system"]
    if lower:
        conditions.append(Message.id > lower)
    stmt = select(Message.id).where(*conditions)
    return len((await db.execute(stmt)).all())


async def _chat_title(db: AsyncSession, chat_id: str) -> str:
    from app.models.chat import Chat

    chat = await db.get(Chat, chat_id)
    return chat.title if chat and chat.title else "Vibe Chat"
