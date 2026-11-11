"""create invites

Revision ID: 45422ad8adcc
Revises: 6b52a8ab0ad9
Create Date: 2026-11-11 20:01:08.569461

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "45422ad8adcc"
down_revision: str | None = "6b52a8ab0ad9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Инвайт-коды регистрации (§5 «Регистрация»): multi-use, в БД только sha256-хэш
    op.create_table(
        "invites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("max_uses", sa.Integer, nullable=True),  # NULL = безлимит
        sa.Column("uses_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("invites")
