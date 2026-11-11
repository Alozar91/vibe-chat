"""create messages and files tables

Revision ID: 41a8e834e49a
Revises: 2400ffeca194
Create Date: 2026-11-11 18:01:48.986350
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "41a8e834e49a"
down_revision: str | None = "2400ffeca194"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(10), nullable=False),  # pending | ready
        sa.Column("bucket", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),  # заявленный клиентом
        sa.Column("real_mime_type", sa.String(255), nullable=True),  # sniffing при complete
        sa.Column("thumb_key", sa.String(512), nullable=True),
        sa.Column("blurhash", sa.String(64), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("uploader_id", sa.String(36), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),  # UUIDv7
        sa.Column("chat_id", sa.String(36), sa.ForeignKey("chats.id"), nullable=False),
        sa.Column("sender_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),  # NULL у system
        sa.Column("type", sa.String(10), nullable=False),  # text | system
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),  # jsonb (параметры system)
        sa.Column("client_ref", sa.String(36), nullable=True),
        sa.Column("reply_to_id", sa.String(36), sa.ForeignKey("messages.id"), nullable=True),
        sa.Column("forward_from_message_id", sa.String(36), nullable=True),
        sa.Column("forward_from_chat_id", sa.String(36), nullable=True),
        sa.Column("forward_snapshot", sa.JSON(), nullable=True),  # jsonb
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("timezone", sa.String(64), nullable=True),  # IANA-пояс отправителя
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Уникальность идемпотентности: одно действие = один ключ (§6)
    op.create_unique_constraint(
        "uq_messages_sender_client_ref_chat",
        "messages",
        ["sender_id", "client_ref", "chat_id"],
    )
    # Главный индекс системы: keyset-пагинация (§6)
    op.create_index("ix_messages_chat_id_id", "messages", ["chat_id", "id"])
    op.create_index(
        "ix_messages_updated_at", "messages", ["chat_id", "updated_at"]
    )  # дельта edit/delete (?updated_after=)
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("file_id", sa.String(36), sa.ForeignKey("files.id"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),  # image | video | file
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.create_index("ix_attachments_message_id", "attachments", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_attachments_message_id", table_name="attachments")
    op.drop_table("attachments")
    op.drop_index("ix_messages_updated_at", table_name="messages")
    op.drop_index("ix_messages_chat_id_id", table_name="messages")
    op.drop_constraint("uq_messages_sender_client_ref_chat", "messages", type_="unique")
    op.drop_table("messages")
    op.drop_table("files")
