"""Сообщения и файлы: REST-роуты (Docs/concept.md §12)."""

from datetime import datetime
from typing import Annotated, Any

from app.api.deps import UserDep
from app.core.config import get_settings
from app.db.session import get_db
from app.models.file import File
from app.models.message import Attachment, Message
from app.schemas.message import (
    FileOut,
    FileUrlOut,
    ForwardIn,
    MessageCreateIn,
    MessageEditIn,
    MessageOut,
    ReactionGroupOut,
    UploadUrlIn,
    UploadUrlOut,
)
from app.services import files as file_service
from app.services import messages as message_service
from app.services import reactions as reaction_service
from app.services import realtime as rt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["messages"])

DbDep = Annotated[AsyncSession, Depends(get_db)]

# Лимит размера файла — конфиг (§7 «ограничение размера — конфигом»); MVP: 100 МБ
MAX_FILE_SIZE = 100 * 1024 * 1024


def _client_ref(idempotency_key: str | None, body_ref: str | None) -> str | None:
    """Идемпотентность: заголовок приоритетнее тела (§6)."""
    return idempotency_key or body_ref


async def _serialize_many(
    db: AsyncSession,
    messages: list[Message],
    attachments: dict[str, list[tuple[Attachment, File]]],
    reactions_map: dict[str, list[dict[str, Any]]] | None = None,
) -> list[MessageOut]:
    """Сериализация списка с реакциями (§6): batch-загрузка, N+1 нет."""
    if reactions_map is None:
        reactions_map = await reaction_service.list_reactions(db, [m.id for m in messages])
    return [
        MessageOut.model_validate(
            message_service.serialize_message(
                m, attachments.get(m.id, []), reactions_map.get(m.id, [])
            ),
            from_attributes=True,
        )
        for m in messages
    ]


@router.get("/chats/{chat_id}/messages", response_model=list[MessageOut])
async def list_messages(
    chat_id: str,
    me: UserDep,
    db: DbDep,
    before: str | None = None,
    after: str | None = None,
    around: str | None = None,
    updated_after: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[MessageOut]:
    messages = await message_service.list_messages(
        db,
        chat_id=chat_id,
        user_id=me.id,
        before=before,
        after=after,
        updated_after=updated_after,
        around=around,
        limit=limit,
    )
    attachments = await message_service.load_attachments(db, [m.id for m in messages])
    return await _serialize_many(db, messages, attachments)


@router.post("/chats/{chat_id}/messages", response_model=MessageOut, status_code=201)
async def send_message(
    chat_id: str,
    body: MessageCreateIn,
    me: UserDep,
    db: DbDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MessageOut:
    message, _created = await message_service.create_message(
        db,
        sender=me,
        chat_id=chat_id,
        text=body.text,
        attachments=[a.model_dump() for a in body.attachments],
        reply_to_id=body.reply_to_id,
        timezone_name=body.timezone,
        client_ref=_client_ref(idempotency_key, None),
    )
    attachments = await message_service.load_attachments(db, [message.id])
    # message.new → участникам через Valkey Pub/Sub (§9); повтор идемпотентного
    # запроса события не дублирует смысл (клиенты дедуплицируют по id, §9)
    await rt.publish_message_new(db, message)
    out = await _serialize_many(db, [message], attachments)
    return out[0]


@router.patch("/messages/{message_id}", response_model=MessageOut)
async def edit_message(message_id: str, body: MessageEditIn, me: UserDep, db: DbDep) -> MessageOut:
    message = await message_service.edit_message(db, message_id=message_id, actor=me, new_text=body.text)
    attachments = await message_service.load_attachments(db, [message.id])
    await rt.publish_message_edited(db, message)
    out = await _serialize_many(db, [message], attachments)
    return out[0]


@router.delete("/messages/{message_id}", response_model=MessageOut)
async def delete_message(message_id: str, me: UserDep, db: DbDep) -> MessageOut:
    message = await message_service.delete_message(db, message_id=message_id, actor=me)
    await rt.publish_message_deleted(db, message)
    # deleted: заглушка без вложений и реакций (§6 — реакции скрыты надгробием)
    return MessageOut.model_validate(message_service.serialize_message(message, [], []))


@router.post("/messages/{message_id}/forward", response_model=list[MessageOut], status_code=201)
async def forward_message(
    message_id: str,
    body: ForwardIn,
    me: UserDep,
    db: DbDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> list[MessageOut]:
    copies = await message_service.forward_message(
        db,
        message_id=message_id,
        actor=me,
        chat_ids=body.chat_ids,
        client_ref=_client_ref(idempotency_key, None),
    )
    attachments = await message_service.load_attachments(db, [m.id for m in copies])
    return await _serialize_many(db, copies, attachments)


# --- Реакции (§6, §12) ---


class ReactionPutIn(BaseModel):
    """PUT /messages/{id}/reactions — {emoji} из фиксированного набора (§6)."""

    emoji: str


@router.put("/messages/{message_id}/reactions", response_model=list[ReactionGroupOut])
async def put_reaction(message_id: str, body: ReactionPutIn, me: UserDep, db: DbDep) -> list[ReactionGroupOut]:
    """Toggle реакции (§6): та же — снять, другая — заменить, нет — поставить.

    Ответ — актуальный список реакций сообщения; всем участникам уходит
    WS-событие reaction.updated (§9).
    """
    reactions_map = await reaction_service.set_reaction(
        db, message_id=message_id, user_id=me.id, emoji=body.emoji
    )
    message = await message_service.get_message_checked(db, message_id)
    groups = reactions_map.get(message_id, [])
    await rt.publish_to_chat(message.chat_id, "reaction.updated", {
        "message_id": message_id,
        "chat_id": message.chat_id,
        "reactions": groups,
    })
    return [ReactionGroupOut.model_validate(g) for g in groups]


# --- Файлы (§8) ---


files_router = APIRouter(tags=["files"])


@files_router.post("/files/upload-url", response_model=UploadUrlOut, status_code=201)
async def create_upload_url(body: UploadUrlIn, me: UserDep, db: DbDep) -> UploadUrlOut:
    if body.size > MAX_FILE_SIZE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "file too large")
    file_id = file_service.new_file_id()
    storage_key = file_service.new_storage_key(file_id)
    file_row = File(
        id=file_id,
        status="pending",
        bucket=get_settings().silo_bucket,
        storage_key=storage_key,
        size_bytes=body.size,
        mime_type=body.mime,
        sha256=body.sha256,
        uploader_id=me.id,
    )
    db.add(file_row)
    await db.commit()
    url = file_service.presign_put(storage_key, body.size, body.mime, get_settings().presign_ttl_seconds)
    return UploadUrlOut(file_id=file_id, upload_url=url, expires_in=get_settings().presign_ttl_seconds)


@files_router.post("/files/{file_id}/complete", response_model=FileOut)
async def complete_upload(file_id: str, me: UserDep, db: DbDep) -> FileOut:
    file_row = await file_service.get_file_checked(db, file_id)
    if file_row.uploader_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not the uploader")
    if file_row.status == "ready":
        return FileOut.model_validate(file_row)  # идемпотентно (§8)

    head = file_service.head_object(file_row.storage_key)
    real_size = int(head.get("ContentLength", 0))
    if real_size != file_row.size_bytes:
        file_row.size_bytes = real_size
    content_type = str(head.get("ContentType", "")) or file_row.mime_type
    # sniffing требует данных; для MVP читаем первые байты через get_object (Range) —
    # упрощение: если Silo недоступен, complete вернёт 502
    data = file_service.read_object_prefix(file_row.storage_key)
    real_mime = file_service.sniff_mime(data, content_type)
    file_row.real_mime_type = real_mime
    file_row.status = "ready"
    thumb = file_service.make_thumbnail_and_blurhash(file_row, data)
    if thumb is not None:
        file_row.thumb_key, file_row.blurhash = thumb
    await db.commit()
    await db.refresh(file_row)
    return FileOut.model_validate(file_row)


@files_router.get("/files/{file_id}/url", response_model=FileUrlOut)
async def get_file_url(file_id: str, me: UserDep, db: DbDep) -> FileUrlOut:
    """Точечные случаи: аватар, превью перед отправкой, освежение URL (§8)."""
    file_row = await file_service.get_file_checked(db, file_id)
    if file_row.status == "pending":
        if file_row.uploader_id != me.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "pending file is visible to uploader only")
    else:
        # ready: uploader или участник чата с вложением (§8 «Доступ к файлам»)
        allowed = await file_service.can_read_file(db, file_row, me.id)
        if not allowed and file_row.uploader_id != me.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "no access to file")
    url = file_service.presign_get_url(
        file_row.storage_key, ttl_seconds=get_settings().presign_ttl_seconds
    )
    return FileUrlOut(url=url, expires_in=get_settings().presign_ttl_seconds)
