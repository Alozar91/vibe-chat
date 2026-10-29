import asyncio
import uuid

from app.core.valkey import get_valkey
from app.db.session import session_factory
from app.models import ChatMember, User
from app.modules.chats import service as chats
from app.modules.messages import service as messages


async def main() -> int:
    suffix = uuid.uuid4().hex[:8]
    async with session_factory() as db:
        u1 = User(kind="human", username=f"smoke_a_{suffix}", full_name="Смоук Один", source="local")
        u2 = User(kind="human", username=f"smoke_b_{suffix}", full_name="Смоук Два", source="local")
        db.add_all([u1, u2])
        await db.commit()

        chat = await chats.create_direct_chat(db, u1.id, u2.id)
        chat_again = await chats.create_direct_chat(db, u1.id, u2.id)
        assert chat.id == chat_again.id, "direct chat dedup"
        member1 = await chats.get_membership(db, chat.id, u1.id)
        member2 = await chats.get_membership(db, chat.id, u2.id)
        assert member1 is not None and member2 is not None

        valkey = get_valkey()
        body1 = f"привет @{u2.username}!"
        msg1, created1 = await messages.send_message(db, valkey, chat, member1, u1.id, {"body": body1}, "idem-1")
        assert created1 and msg1["seq"] == 1 and msg1["mentions"], "первое сообщение с упоминанием"

        msg1_retry, created2 = await messages.send_message(db, valkey, chat, member1, u1.id, {"body": body1}, "idem-1")
        assert not created2 and msg1_retry["seq"] == msg1["seq"], "идемпотентность"

        msg2, created3 = await messages.send_message(db, valkey, chat, member2, u2.id, {"body": "ответ"}, None)
        assert created3 and msg2["seq"] == 2

        edited = await messages.edit_message(db, valkey, chat, member2, msg2["seq"], u2.id, "ответ (исправлен)")
        assert edited["edited_at"], "редактирование"

        listing = await messages.list_messages(db, chat, u1.id, 50, None, None)
        assert len(listing["items"]) == 2 and listing["items"][-1]["seq"] == 2

        unread = await chats.mark_read(db, chat, member1, 2)
        assert unread == 0, "прочитано"

        await messages.delete_message(db, valkey, chat, member2, msg2["seq"], u2.id)
        after_delete = await messages.get_message(db, chat, u1.id, msg2["seq"])
        assert after_delete["deleted_at"] and after_delete["body"] == "", "tombstone"

        members = (await db.execute(
            __import__("sqlalchemy").select(ChatMember).where(ChatMember.chat_id == chat.id)
        )).scalars().all()
        assert len(members) == 2

        import httpx

        from app.modules.media import service as media

        await asyncio.to_thread(media.ensure_bucket)
        intent = await media.create_upload_intent(db, u1.id, "smoke.txt", "text/plain", 5)
        async with httpx.AsyncClient(timeout=30) as http:
            put = await http.put(intent["upload_url"], content=b"hello")
            assert put.status_code in (200, 201), f"PUT в S3: {put.status_code}"
            file_id = uuid.UUID(intent["file_id"])
            done = await media.complete_upload(db, u1.id, file_id)
            assert done["status"] == "ready"
            link = await media.get_download_url(db, file_id, u1.id)
            loaded = await http.get(link["url"])
            assert loaded.content == b"hello", "содержимое файла"
        try:
            await media.get_download_url(db, file_id, u2.id)
            raise AssertionError("чужой файл не должен быть доступен до вложения")
        except Exception:
            pass
        msg3, _ = await messages.send_message(db, valkey, chat, member1, u1.id, {"body": "", "attachments": [file_id]}, None)
        assert msg3["type"] == "file" and msg3["attachments"], "вложение в сообщении"
        link2 = await media.get_download_url(db, file_id, u2.id)
        assert link2["url"], "доступ через членство в чате"

        await db.delete(chat)
        file_row = await db.get(__import__("app.models", fromlist=["File"]).File, file_id)
        await db.delete(file_row)
        await db.delete(u1)
        await db.delete(u2)
        await db.commit()

    print("SMOKE OK: dedup, seq, idempotency, mentions, edit, read, delete, S3 presigned, права на файлы")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
