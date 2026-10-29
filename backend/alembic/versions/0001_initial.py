"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_KIND = postgresql.ENUM("human", "bot", name="user_kind", create_type=True)
USER_ROLE = postgresql.ENUM("owner", "admin", "member", name="user_role", create_type=True)
USER_STATUS = postgresql.ENUM("active", "disabled", name="user_status", create_type=True)
CHAT_TYPE = postgresql.ENUM("direct", "group", name="chat_type", create_type=True)
CHAT_MEMBER_ROLE = postgresql.ENUM(
    "owner", "admin", "member", name="chat_member_role", create_type=True
)
CHAT_MEMBER_STATUS = postgresql.ENUM(
    "invited", "active", "left", "removed", "banned", name="chat_member_status", create_type=True
)
MESSAGE_TYPE = postgresql.ENUM(
    "text", "image", "file", "audio", "video", "card", "system", name="message_type", create_type=True
)

UUID_PK = "gen_random_uuid()"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text(UUID_PK)),
        sa.Column("kind", USER_KIND, nullable=False),
        sa.Column("keycloak_sub", sa.String(64), unique=True),
        sa.Column("username", sa.String(255), unique=True, nullable=False),
        sa.Column("full_name", sa.Text, nullable=False),
        sa.Column("email", sa.String(255), unique=True),
        sa.Column("phone", sa.String(32)),
        sa.Column("title", sa.Text),
        sa.Column("role", USER_ROLE, nullable=False),
        sa.Column("status", USER_STATUS, nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("notification_settings", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_deleted", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "users_full_name_trgm_idx",
        "users",
        ["full_name"],
        postgresql_using="gin",
        postgresql_ops={"full_name": "gin_trgm_ops"},
    )

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer, primary_key=True, server_default=sa.text("1")),
        sa.Column("org_name", sa.Text, nullable=False),
        sa.Column("settings", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("id = 1", name="app_settings_singleton"),
    )
    op.execute("INSERT INTO app_settings (id, org_name) VALUES (1, 'Вайб')")

    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text(UUID_PK)),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("push_token", sa.Text),
        sa.Column("webpush_endpoint", sa.Text),
        sa.Column("webpush_keys", postgresql.JSONB),
        sa.Column("device_id", sa.String(128)),
        sa.Column("app_version", sa.String(64)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("devices_user_idx", "devices", ["user_id"])
    op.create_index(
        "devices_push_token_uq",
        "devices",
        ["platform", "push_token"],
        unique=True,
        postgresql_where=sa.text("push_token IS NOT NULL"),
    )
    op.create_index(
        "devices_webpush_uq",
        "devices",
        ["webpush_endpoint"],
        unique=True,
        postgresql_where=sa.text("webpush_endpoint IS NOT NULL"),
    )

    op.create_table(
        "chats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text(UUID_PK)),
        sa.Column("type", CHAT_TYPE, nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("avatar_url", sa.Text),
        sa.Column("description", sa.Text),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("is_public", sa.Boolean, nullable=False),
        sa.Column("members_count", sa.Integer, nullable=False),
        sa.Column("last_message_seq", sa.BigInteger, nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("settings", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("chats_last_message_idx", "chats", [sa.text("last_message_at DESC")])

    op.create_table(
        "direct_chats",
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_a", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("user_b", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("user_a <> user_b", name="direct_chats_users_distinct"),
    )
    op.create_index(
        "direct_chats_pair_uq",
        "direct_chats",
        [sa.text("LEAST(user_a, user_b)"), sa.text("GREATEST(user_a, user_b)")],
        unique=True,
    )

    op.create_table(
        "chat_members",
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", CHAT_MEMBER_ROLE, nullable=False),
        sa.Column("status", CHAT_MEMBER_STATUS, nullable=False),
        sa.Column("notifications", sa.String(16), nullable=False),
        sa.Column("muted_until", sa.DateTime(timezone=True)),
        sa.Column("last_read_seq", sa.BigInteger, nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True)),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True)),
    )
    op.create_index("chat_members_user_idx", "chat_members", ["user_id", "status"])
    op.create_index("chat_members_chat_idx", "chat_members", ["chat_id", "status"])

    op.create_table(
        "chat_invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text(UUID_PK)),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(64), unique=True, nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("domain_limit", sa.String(255)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("max_uses", sa.Integer),
        sa.Column("uses", sa.Integer, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("chat_invites_chat_idx", "chat_invites", ["chat_id"])

    op.create_table(
        "messages",
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("seq", sa.BigInteger, primary_key=True),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", MESSAGE_TYPE, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("data", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("reply_to_seq", sa.BigInteger),
        sa.Column("client_idempotency_key", sa.String(64)),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR,
            sa.Computed("to_tsvector('russian', body)", persisted=True),
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "messages_idempotency_uq",
        "messages",
        ["chat_id", "sender_id", "client_idempotency_key"],
        unique=True,
        postgresql_where=sa.text("client_idempotency_key IS NOT NULL"),
    )
    op.create_index("messages_page_idx", "messages", ["chat_id", sa.text("seq DESC")])
    op.create_index("messages_fts_idx", "messages", ["search_vector"], postgresql_using="gin")
    op.create_index("messages_created_idx", "messages", [sa.text("created_at DESC")])

    op.create_table(
        "files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text(UUID_PK)),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.Text, nullable=False),
        sa.Column("thumbnail_key", sa.Text),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("av_status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("files_owner_idx", "files", ["owner_id"])

    op.create_table(
        "message_attachments",
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_seq", sa.BigInteger, primary_key=True),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("files.id"), primary_key=True),
        sa.Column("position", sa.SmallInteger, nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_id", "message_seq"],
            ["messages.chat_id", "messages.seq"],
            name="fk_message_attachments_message",
            ondelete="CASCADE",
        ),
    )
    op.create_index("message_attachments_file_idx", "message_attachments", ["file_id"])

    op.add_column(
        "users",
        sa.Column(
            "avatar_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("files.id", use_alter=True, name="fk_users_avatar_file", ondelete="SET NULL"),
        ),
    )

    op.create_table(
        "message_mentions",
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_seq", sa.BigInteger, primary_key=True),
        sa.Column("mentioned_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_id", "message_seq"],
            ["messages.chat_id", "messages.seq"],
            name="fk_message_mentions_message",
            ondelete="CASCADE",
        ),
    )
    op.create_index("message_mentions_user_idx", "message_mentions", ["mentioned_user_id", "chat_id"])

    op.create_table(
        "message_reactions",
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_seq", sa.BigInteger, primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("emoji", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_id", "message_seq"],
            ["messages.chat_id", "messages.seq"],
            name="fk_message_reactions_message",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "bots",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("description", sa.Text),
        sa.Column("webhook_url", sa.Text),
        sa.Column("webhook_secret_ref", sa.String(128)),
        sa.Column("is_enabled", sa.Boolean, nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "bot_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text(UUID_PK)),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bots.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("scopes", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "bot_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text(UUID_PK)),
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bots.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "bot_subscriptions_uq",
        "bot_subscriptions",
        ["bot_id", "event_type", sa.text("COALESCE(chat_id, '00000000-0000-0000-0000-000000000000'::uuid)")],
        unique=True,
    )

    op.create_table(
        "bot_commands",
        sa.Column("bot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bots.user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("command", sa.String(64), primary_key=True),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "outbox_events",
        sa.Column("seq", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True)),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "outbox_unpublished_idx",
        "outbox_events",
        ["created_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_index("outbox_chat_seq_idx", "outbox_events", ["chat_id", "seq"])

    op.create_table(
        "login_events",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("origin", sa.String(16)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("ip", postgresql.INET),
        sa.Column("user_agent", sa.Text),
        sa.Column("error_code", sa.String(64)),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("login_events_user_idx", "login_events", ["user_id", sa.text("created_at DESC")])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64)),
        sa.Column("entity_id", sa.String(64)),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip", postgresql.INET),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("audit_logs_time_idx", "audit_logs", [sa.text("created_at DESC")])
    op.create_index("audit_logs_entity_idx", "audit_logs", ["entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("login_events")
    op.drop_table("outbox_events")
    op.drop_table("bot_commands")
    op.drop_table("bot_subscriptions")
    op.drop_table("bot_tokens")
    op.drop_table("bots")
    op.drop_table("message_reactions")
    op.drop_table("message_mentions")
    op.drop_constraint("fk_users_avatar_file", "users", type_="foreignkey")
    op.drop_column("users", "avatar_file_id")
    op.drop_table("message_attachments")
    op.drop_table("files")
    op.drop_table("messages")
    op.drop_table("chat_invites")
    op.drop_table("chat_members")
    op.drop_table("direct_chats")
    op.drop_table("chats")
    op.drop_table("devices")
    op.drop_table("app_settings")
    op.drop_table("users")
    for name in (
        "message_type",
        "chat_member_status",
        "chat_member_role",
        "chat_type",
        "user_status",
        "user_role",
        "user_kind",
    ):
        op.execute(f"DROP TYPE IF EXISTS {name}")
