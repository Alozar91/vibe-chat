"""add user personal fields

Revision ID: 6b52a8ab0ad9
Revises: c06b526ab348
Create Date: 2026-11-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6b52a8ab0ad9"
down_revision: str | None = "c06b526ab348"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Персональные данные — на уровне системы (§5), из JWT-клеймов не берутся
    op.add_column("users", sa.Column("first_name", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("email", sa.String(320), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "email")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
