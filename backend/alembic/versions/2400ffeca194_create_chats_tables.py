"""create chats tables

Revision ID: 2400ffeca194
Revises: 11d4a165ed7f
Create Date: 2026-11-11 17:32:21.998783
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2400ffeca194"
down_revision: str | None = "11d4a165ed7f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("avatar_file_id", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "chat_members",
        sa.Column("chat_id", sa.String(36), sa.ForeignKey("chats.id"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_read_message_id", sa.String(36), nullable=True),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "direct_chat_keys",
        sa.Column("chat_id", sa.String(36), sa.ForeignKey("chats.id"), primary_key=True),
        sa.Column("user_a", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("user_b", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("user_a", "user_b", name="uq_direct_pair"),
    )


def downgrade() -> None:
    op.drop_table("direct_chat_keys")
    op.drop_table("chat_members")
    op.drop_table("chats")
