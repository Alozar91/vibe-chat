"""message id (uuid v7) for external references

Revision ID: 0002_message_id
Revises: 0001_initial
Create Date: 2026-10-29
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_message_id"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.create_unique_constraint("messages_id_uq", "messages", ["id"])
    op.alter_column("messages", "id", existing_type=postgresql.UUID(as_uuid=True), server_default=None)


def downgrade() -> None:
    op.drop_constraint("messages_id_uq", "messages", type_="unique")
    op.drop_column("messages", "id")
