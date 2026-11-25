"""create device_tokens

Revision ID: a3f9c2d81e47
Revises: 7c1a4f2b9e30
Create Date: 2026-11-25 17:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3f9c2d81e47"
down_revision: str | None = "7c1a4f2b9e30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Device-токены пушей (Docs/android.md §3.8, этап 6): FCM-токен → пользователь.
    # PK — токен (upsert при регистрации); last_pushed_message_id — контрольная
    # точка агрегации непрочитанных.
    op.create_table(
        "device_tokens",
        sa.Column("token", sa.String(255), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("last_pushed_message_id", sa.String(36), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("device_tokens")
