"""create bot profiles

Revision ID: eabdb8a976e7
Revises: 41a8e834e49a
Create Date: 2026-11-11 21:12:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "eabdb8a976e7"
down_revision: str | None = "41a8e834e49a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_profiles",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("miniapp_url", sa.String(512), nullable=True),
        sa.Column("miniapp_name", sa.String(255), nullable=True),
        sa.Column("webhook_url", sa.String(512), nullable=True),  # post-MVP
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("bot_profiles")
