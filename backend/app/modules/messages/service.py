import uuid
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from valkey.asyncio import Valkey

from app.config import get_settings
from app.core.errors import bad_request, conflict, forbidden, not_found
from app.core.mentions import parse_mentions
from app.core.outbox import add_event
from app.core.permissions import ChatRole
from app.core.timeutil import utcnow
from app.core.valkey import publish_event
from app.models import (
    BotCommand,
    Chat,
    ChatMember,
    ChatMemberStatus,
    File,
    Message,
    MessageAttachment,
    MessageMention,
    MessageReaction,
    MessageType,
    User,
)


def serialize_message(message: Message, related: dict[str, Any]) -> dict[str, Any]:
    deleted = message.deleted_at is not None
    return {
        "id": str(message.id),
        "chat_id": str(message.chat_id),
        "seq": message.seq,
        "sender_id": str(message.sender_id),
        "type": str(message.type),
        "body": "" if deleted else message.body,
        "data": {} if deleted else (message.data or {}),
        "reply_to_seq": message.reply_to_seq,
        "mentions": [] if deleted else related.get("mentions", []),
        "mentions_all": False if deleted else bool((message.data or {}).get("mentions_all")),
        "attachments": [] if deleted else related.get("attachments", []),
        "reactions": related.get("reactions", {}),
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
        "deleted_at": message.deleted_at.isoformat() if message.deleted_at else None,
        "created_at": message.created_at.isoformat(),
    }


async def _load_attachments(
    session: AsyncSession, chat_id: uuid.UUID, seqs: list[int]
) -> dict[int, list[dict[str, Any]]]:
    rows = (
        await session.execute(
            select(MessageAttachment, File)
            .join(File, File.id == MessageAttachment.file_id)
            .where(MessageAttachment.chat_id == chat_id, MessageAttachment.message_seq.in_(seqs))
            .order_by(MessageAttachment.message_seq, MessageAttachment.position)
        )
    ).all()
    out: dict[int, list[dict[str, Any]]] = {}
    for att, file in rows:
        out.setdefault(att.message_seq, []).append(
            {
                "file_id": str(file.id),
                "name": file.name,
                "mime_type": file.mime_type,
                "size_bytes": file.size_bytes,
                "width": file.width,
                "height": file.height,
                "thumbnail_url": f"/v1/media/{file.id}/url?variant=thumb" if file.thumbnail_key else None,
                "url": f"/v1/media/{file.id}/url",
            }
        )
    return out


async def _load_mentions(
    session: AsyncSession, chat_id: uuid.UUID, seqs: list[int]
) -> dict[int, list[dict[str, Any]]]:
    rows = (
        await session.execute(
            select(MessageMention, User)
            .join(User, User.id == MessageMention.mentioned_user_id)
            .where(MessageMention.chat_id == chat_id, MessageMention.message_seq.in_(seqs))
        )
    ).all()
    out: dict[int, list[dict[str, Any]]] = {}
    for mention, user in rows:
        out.setdefault(mention.message_seq, []).append(
            {"user_id": str(user.id), "username": user.username}
        )
    return out


async def _load_reactions(
    session: AsyncSession, chat_id: uuid.UUID, seqs: list[int], viewer_id: uuid.UUID
) -> dict[int, dict[str, dict[str, Any]]]:
    rows = (
        await session.scalars(
            select(MessageReaction).where(
                MessageReaction.chat_id == chat_id, MessageReaction.message_seq.in_(seqs)
            )
        )
    ).all()
    out: dict[int, dict[str, dict[str, Any]]] = {}
    for reaction in rows:
        agg = out.setdefault(reaction.message_seq, {}).setdefault(
            reaction.emoji, {"count": 0, "my": False}
        )
        agg["count"] += 1
        if reaction.user_id == viewer_id:
            agg["my"] = True
    return out


async def load_related(
    session: AsyncSession, chat_id: uuid.UUID, seqs: list[int], viewer_id: uuid.UUID
) -> dict[int, dict[str, Any]]:
    if not seqs:
        return {}
    attachments = await _load_attachments(session, chat_id, seqs)
    mentions = await _load_mentions(session, chat_id, seqs)
    reactions = await _load_reactions(session, chat_id, seqs, viewer_id)
    return {
        seq: {
            "attachments": attachments.get(seq, []),
            "mentions": mentions.get(seq, []),
            "reactions": reactions.get(seq, {}),
        }
        for seq in seqs
    }


def _message_type_for(mime_types: list[str]) -> MessageType:
    if not mime_types:
        return MessageType.TEXT
    if all(m.startswith("image/") for m in mime_types):
        return MessageType.IMAGE
    if all(m.startswith("video/") for m in mime_types):
        return MessageType.VIDEO
    if all(m.startswith("audio/") for m in mime_types):
        return MessageType.AUDIO
    return MessageType.FILE


async def _get_message(session: AsyncSession, chat_id: uuid.UUID, seq: int) -> Message:
    message = (
        await session.scalars(
            select(Message).where(Message.chat_id == chat_id, Message.seq == seq)
        )
    ).one_or_none()
    if message is None:
        raise not_found("Сообщение")
    return message


async def _maybe_bot_command(
    session: AsyncSession, chat: Chat, message: Message, body: str
) -> None:
    if not body.startswith("/"):
        return
    rows = (
        await session.execute(
            select(BotCommand.bot_id, BotCommand.command)
            .join(ChatMember, ChatMember.user_id == BotCommand.bot_id)
            .where(ChatMember.chat_id == chat.id, ChatMember.status == ChatMemberStatus.ACTIVE)
        )
    ).all()
    for bot_id, command in rows:
        if body == command or body.startswith(command + " "):
            args = body[len(command):].strip()
            await add_event(
                session,
                aggregate_type="message",
                aggregate_id=f"{chat.id}:{message.seq}",
                event_type="message.command",
                chat_id=chat.id,
                payload={
                    "chat_id": str(chat.id),
                    "seq": message.seq,
                    "bot_user_id": str(bot_id),
                    "command": command,
                    "args": args,
                    "sender_id": str(message.sender_id),
                },
            )


async def send_message(
    db: AsyncSession,
    valkey: Valkey,
    chat: Chat,
    member: ChatMember,
    sender_id: uuid.UUID,
    payload: dict[str, Any],
    idem_key: str | None,
) -> tuple[dict[str, Any], bool]:
    settings = get_settings()
    body = str(payload.get("body") or "")
    if len(body) > settings.message_max_length:
        raise bad_request(f"body: до {settings.message_max_length} символов")
    attachment_ids = payload.get("attachments") or []
    if len(attachment_ids) > settings.max_attachments:
        raise bad_request(f"attachments: до {settings.max_attachments} вложений")
    forward_refs = payload.get("forward") or []
    if len(forward_refs) > 10:
        raise bad_request("forward: до 10 сообщений")
    reply_to_seq = payload.get("reply_to_seq")

    if idem_key:
        existing = (
            await db.scalars(
                select(Message).where(
                    Message.chat_id == chat.id,
                    Message.sender_id == sender_id,
                    Message.client_idempotency_key == idem_key,
                )
            )
        ).one_or_none()
        if existing is not None:
            related = await load_related(db, chat.id, [existing.seq], sender_id)
            return serialize_message(existing, related[existing.seq]), False

    if reply_to_seq is not None:
        reply = (
            await db.scalars(
                select(Message).where(Message.chat_id == chat.id, Message.seq == reply_to_seq)
            )
        ).one_or_none()
        if reply is None:
            raise not_found("Сообщение для ответа")

    files_rows: list[File] = []
    if attachment_ids:
        try:
            wanted = {uuid.UUID(str(fid)) for fid in attachment_ids}
        except ValueError as exc:
            raise bad_request("attachments: некорректный file_id") from exc
        found = {f.id: f for f in (await db.scalars(select(File).where(File.id.in_(wanted)))).all()}
        for fid in wanted:
            file = found.get(fid)
            if file is None or file.owner_id != sender_id or file.av_status == "infected":
                raise bad_request("Вложение недоступно")
            files_rows.append(file)

    forwarded_from: list[dict[str, Any]] = []
    forwarded_file_ids: list[uuid.UUID] = []
    for ref in forward_refs:
        try:
            src_chat_id = uuid.UUID(str(ref.get("chat_id")))
            src_seq = int(ref.get("seq"))
        except (TypeError, ValueError) as exc:
            raise bad_request("forward: [{chat_id, seq}]") from exc
        src_member = (
            await db.scalars(
                select(ChatMember).where(
                    ChatMember.chat_id == src_chat_id,
                    ChatMember.user_id == sender_id,
                    ChatMember.status == ChatMemberStatus.ACTIVE,
                )
            )
        ).one_or_none()
        if src_member is None:
            raise forbidden("Нет доступа к пересылаемому сообщению")
        src_msg = (
            await db.scalars(
                select(Message).where(Message.chat_id == src_chat_id, Message.seq == src_seq)
            )
        ).one_or_none()
        if src_msg is None or src_msg.deleted_at is not None:
            raise not_found("Пересылаемое сообщение")
        src_sender = await db.get(User, src_msg.sender_id)
        forwarded_from.append(
            {
                "chat_id": str(src_chat_id),
                "seq": src_seq,
                "sender_id": str(src_msg.sender_id),
                "sender_name": src_sender.full_name if src_sender else None,
                "sent_at": src_msg.created_at.isoformat(),
            }
        )
        src_files = (
            await db.scalars(
                select(MessageAttachment).where(
                    MessageAttachment.chat_id == src_chat_id,
                    MessageAttachment.message_seq == src_seq,
                )
            )
        ).all()
        forwarded_file_ids.extend(att.file_id for att in src_files)

    member_rows = (
        await db.execute(
            select(ChatMember, User)
            .join(User, User.id == ChatMember.user_id)
            .where(ChatMember.chat_id == chat.id, ChatMember.status == ChatMemberStatus.ACTIVE)
        )
    ).all()
    member_usernames = {user.username.lower(): user.id for _, user in member_rows}
    mentions, mentions_all = parse_mentions(
        body, member_usernames, ChatRole(member.role), chat.members_count, settings.all_mention_threshold
    )

    msg_type = _message_type_for([f.mime_type for f in files_rows])
    message = Message(
        chat_id=chat.id,
        seq=0,
        sender_id=sender_id,
        type=msg_type,
        body=body,
        reply_to_seq=reply_to_seq,
        client_idempotency_key=idem_key,
        data={"forwarded_from": forwarded_from, "mentions_all": mentions_all},
    )

    nested = await db.begin_nested()
    try:
        seq = (
            await db.execute(
                update(Chat)
                .where(Chat.id == chat.id)
                .values(last_message_seq=Chat.last_message_seq + 1, last_message_at=utcnow())
                .returning(Chat.last_message_seq)
            )
        ).scalar_one()
        message.seq = seq
        db.add(message)
        await db.flush()
        position = 0
        for file in files_rows:
            db.add(
                MessageAttachment(chat_id=chat.id, message_seq=seq, file_id=file.id, position=position)
            )
            position += 1
        for fid in forwarded_file_ids:
            db.add(MessageAttachment(chat_id=chat.id, message_seq=seq, file_id=fid, position=position))
            position += 1
        for uid in mentions:
            db.add(MessageMention(chat_id=chat.id, message_seq=seq, mentioned_user_id=uid))
        related = await load_related(db, chat.id, [seq], sender_id)
        serialized = serialize_message(message, related[seq])
        await add_event(
            db,
            aggregate_type="message",
            aggregate_id=f"{chat.id}:{seq}",
            event_type="message.created",
            chat_id=chat.id,
            payload={"chat_id": str(chat.id), "seq": seq, "message": serialized},
        )
        await _maybe_bot_command(db, chat, message, body)
    except IntegrityError:
        await nested.rollback()
        if idem_key:
            existing = (
                await db.scalars(
                    select(Message).where(
                        Message.chat_id == chat.id,
                        Message.sender_id == sender_id,
                        Message.client_idempotency_key == idem_key,
                    )
                )
            ).one_or_none()
            if existing is not None:
                related = await load_related(db, chat.id, [existing.seq], sender_id)
                return serialize_message(existing, related[existing.seq]), False
        raise conflict("Не удалось создать сообщение") from None
    else:
        await nested.commit()

    await db.commit()
    await publish_event({"type": "message.new", "chat_id": str(chat.id), "data": serialized})
    return serialized, True


async def list_messages(
    db: AsyncSession,
    chat: Chat,
    viewer_id: uuid.UUID,
    limit: int,
    before_seq: int | None,
    after_seq: int | None,
) -> dict[str, Any]:
    stmt = select(Message).where(Message.chat_id == chat.id)
    if before_seq is not None:
        stmt = stmt.where(Message.seq < before_seq).order_by(Message.seq.desc())
    elif after_seq is not None:
        stmt = stmt.where(Message.seq > after_seq).order_by(Message.seq.asc())
    else:
        stmt = stmt.order_by(Message.seq.desc())
    rows = list((await db.scalars(stmt.limit(limit + 1))).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    if after_seq is None:
        rows.reverse()
    related = await load_related(db, chat.id, [m.seq for m in rows], viewer_id)
    result: dict[str, Any] = {
        "items": [serialize_message(m, related[m.seq]) for m in rows],
        "has_more": has_more,
    }
    if rows and after_seq is None:
        result["next_before_seq"] = rows[0].seq
    return result


async def get_message(
    db: AsyncSession, chat: Chat, viewer_id: uuid.UUID, seq: int
) -> dict[str, Any]:
    message = await _get_message(db, chat.id, seq)
    related = await load_related(db, chat.id, [seq], viewer_id)
    return serialize_message(message, related[seq])


async def edit_message(
    db: AsyncSession,
    valkey: Valkey,
    chat: Chat,
    member: ChatMember,
    seq: int,
    editor_id: uuid.UUID,
    body: str,
) -> dict[str, Any]:
    message = await _get_message(db, chat.id, seq)
    if message.sender_id != editor_id:
        raise forbidden("Редактировать можно только свои сообщения")
    if message.deleted_at is not None:
        raise bad_request("Сообщение удалено")
    if message.type == MessageType.SYSTEM:
        raise bad_request("Системное сообщение нельзя изменить")
    settings = get_settings()
    if len(body) > settings.message_max_length:
        raise bad_request(f"body: до {settings.message_max_length} символов")

    member_rows = (
        await db.execute(
            select(ChatMember, User)
            .join(User, User.id == ChatMember.user_id)
            .where(ChatMember.chat_id == chat.id, ChatMember.status == ChatMemberStatus.ACTIVE)
        )
    ).all()
    member_usernames = {user.username.lower(): user.id for _, user in member_rows}
    mentions, mentions_all = parse_mentions(
        body, member_usernames, ChatRole(member.role), chat.members_count, settings.all_mention_threshold
    )
    await db.execute(
        sa_delete(MessageMention).where(
            MessageMention.chat_id == chat.id, MessageMention.message_seq == seq
        )
    )
    for uid in mentions:
        db.add(MessageMention(chat_id=chat.id, message_seq=seq, mentioned_user_id=uid))

    message.body = body
    message.edited_at = utcnow()
    message.data = {**message.data, "mentions_all": mentions_all}
    await add_event(
        db,
        aggregate_type="message",
        aggregate_id=f"{chat.id}:{seq}",
        event_type="message.updated",
        chat_id=chat.id,
        payload={
            "chat_id": str(chat.id),
            "seq": seq,
            "id": str(message.id),
            "body": body,
            "edited_at": message.edited_at.isoformat(),
        },
    )
    await db.commit()
    related = await load_related(db, chat.id, [seq], editor_id)
    serialized = serialize_message(message, related[seq])
    await publish_event({"type": "message.updated", "chat_id": str(chat.id), "data": serialized})
    return serialized


async def delete_message(
    db: AsyncSession,
    valkey: Valkey,
    chat: Chat,
    member: ChatMember,
    seq: int,
    actor_id: uuid.UUID,
) -> None:
    message = await _get_message(db, chat.id, seq)
    if message.deleted_at is not None:
        return
    from app.core.audit import log_action
    from app.core.permissions import can_delete_other_message

    if message.sender_id != actor_id:
        if not can_delete_other_message(member.role):
            raise forbidden("Удалять чужие сообщения может владелец/админ чата")
        await log_action(
            db,
            actor_id=actor_id,
            action="message.deleted",
            entity_type="message",
            entity_id=f"{chat.id}:{seq}",
        )
    message.deleted_at = utcnow()
    message.body = ""
    await add_event(
        db,
        aggregate_type="message",
        aggregate_id=f"{chat.id}:{seq}",
        event_type="message.deleted",
        chat_id=chat.id,
        payload={"chat_id": str(chat.id), "seq": seq, "id": str(message.id)},
    )
    await db.commit()
    await publish_event(
        {
            "type": "message.deleted",
            "chat_id": str(chat.id),
            "data": {"chat_id": str(chat.id), "seq": seq, "id": str(message.id)},
        }
    )
