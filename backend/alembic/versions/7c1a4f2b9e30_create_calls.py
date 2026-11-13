"""create calls

Revision ID: 7c1a4f2b9e30
Revises: 45422ad8adcc
Create Date: 2026-11-13 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c1a4f2b9e30"
down_revision: str | None = "45422ad8adcc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chat_id", sa.String(36), sa.ForeignKey("chats.id"), nullable=False),
        sa.Column("initiator_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),  # audio | video
        sa.Column("status", sa.String(10), nullable=False),  # ringing | active | ended
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_calls_chat_created", "calls", ["chat_id", "created_at"])
    op.create_table(
        "call_participants",
        sa.Column("call_id", sa.String(36), sa.ForeignKey("calls.id"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("call_participants")
    op.drop_index("ix_calls_chat_created", table_name="calls")
    op.drop_table("calls")
