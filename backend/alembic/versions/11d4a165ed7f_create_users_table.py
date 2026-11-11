"""create users table

Revision ID: 11d4a165ed7f
Revises:
Create Date: 2026-11-11 16:55:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "11d4a165ed7f"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("keycloak_sub", sa.String(36), unique=True, nullable=True, index=True),
        sa.Column("username", sa.String(255), unique=True, nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("avatar_file_id", sa.String(36), nullable=True),
        sa.Column("is_bot", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_platform_admin", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("time_display", sa.String(20), nullable=False, server_default="browser"),
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("users")
