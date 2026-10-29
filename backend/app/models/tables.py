import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


ZERO_UUID = "00000000-0000-0000-0000-000000000000"


class UserKind(enum.StrEnum):
    HUMAN = "human"
    BOT = "bot"


class UserRole(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class UserStatus(enum.StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ChatType(enum.StrEnum):
    DIRECT = "direct"
    GROUP = "group"


class ChatMemberRole(enum.StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class ChatMemberStatus(enum.StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    LEFT = "left"
    REMOVED = "removed"
    BANNED = "banned"


class MessageType(enum.StrEnum):
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    AUDIO = "audio"
    VIDEO = "video"
    CARD = "card"
    SYSTEM = "system"


def _enum(py_enum: type[enum.Enum], name: str, create: bool = False) -> Enum:
    return Enum(
        py_enum,
        name=name,
        native_enum=True,
        create_type=create,
        values_callable=lambda cls: [e.value for e in cls],
        validate_strings=True,
    )


EnumUserKind = _enum(UserKind, "user_kind", create=True)
EnumUserRole = _enum(UserRole, "user_role")
EnumUserStatus = _enum(UserStatus, "user_status")
EnumChatType = _enum(ChatType, "chat_type", create=True)
EnumChatMemberRole = _enum(ChatMemberRole, "chat_member_role", create=True)
EnumChatMemberStatus = _enum(ChatMemberStatus, "chat_member_status", create=True)
EnumMessageType = _enum(MessageType, "message_type", create=True)


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    kind: Mapped[UserKind] = mapped_column(EnumUserKind, default=UserKind.HUMAN, nullable=False)
    keycloak_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(EnumUserRole, default=UserRole.MEMBER, nullable=False)
    status: Mapped[UserStatus] = mapped_column(EnumUserStatus, default=UserStatus.ACTIVE, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="local", nullable=False)
    notification_settings: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False)
    avatar_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", use_alter=True, name="fk_users_avatar_file", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()

    __table_args__ = (
        Index(
            "users_full_name_trgm_idx",
            "full_name",
            postgresql_using="gin",
            postgresql_ops={"full_name": "gin_trgm_ops"},
        ),
    )


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, server_default=text("1"))
    org_name: Mapped[str] = mapped_column(Text, nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    push_token: Mapped[str | None] = mapped_column(Text)
    webpush_endpoint: Mapped[str | None] = mapped_column(Text)
    webpush_keys: Mapped[dict | None] = mapped_column(JSONB)
    device_id: Mapped[str | None] = mapped_column(String(128))
    app_version: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        Index(
            "devices_push_token_uq",
            "platform",
            "push_token",
            unique=True,
            postgresql_where=text("push_token IS NOT NULL"),
        ),
        Index(
            "devices_webpush_uq",
            "webpush_endpoint",
            unique=True,
            postgresql_where=text("webpush_endpoint IS NOT NULL"),
        ),
        Index("devices_user_idx", "user_id"),
    )


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    type: Mapped[ChatType] = mapped_column(EnumChatType, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_public: Mapped[bool] = mapped_column(default=False, nullable=False)
    members_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_message_seq: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("chats_last_message_idx", last_message_at.desc()),)


class DirectChat(Base):
    __tablename__ = "direct_chats"

    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    user_a: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    user_b: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        CheckConstraint("user_a <> user_b", name="direct_chats_users_distinct"),
        Index(
            "direct_chats_pair_uq",
            func.least(user_a, user_b),
            func.greatest(user_a, user_b),
            unique=True,
        ),
    )


class ChatMember(Base):
    __tablename__ = "chat_members"

    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[ChatMemberRole] = mapped_column(
        EnumChatMemberRole, default=ChatMemberRole.MEMBER, nullable=False
    )
    status: Mapped[ChatMemberStatus] = mapped_column(
        EnumChatMemberStatus, default=ChatMemberStatus.ACTIVE, nullable=False
    )
    notifications: Mapped[str] = mapped_column(String(16), default="all", nullable=False)
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_read_seq: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    joined_at: Mapped[datetime] = _ts()
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("chat_members_user_idx", "user_id", "status"),
        Index("chat_members_chat_idx", "chat_id", "status"),
    )


class ChatInvite(Base):
    __tablename__ = "chat_invites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    domain_limit: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int | None] = mapped_column()
    uses: Mapped[int] = mapped_column(default=0, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (Index("chat_invites_chat_idx", "chat_id"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid7)
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    type: Mapped[MessageType] = mapped_column(
        EnumMessageType, default=MessageType.TEXT, nullable=False
    )
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False)
    reply_to_seq: Mapped[int | None] = mapped_column(BigInteger)
    client_idempotency_key: Mapped[str | None] = mapped_column(String(64))
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('russian', body)", persisted=True),
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        Index(
            "messages_idempotency_uq",
            "chat_id",
            "sender_id",
            "client_idempotency_key",
            unique=True,
            postgresql_where=text("client_idempotency_key IS NOT NULL"),
        ),
        Index("messages_page_idx", "chat_id", seq.desc()),
        Index("messages_fts_idx", "search_vector", postgresql_using="gin"),
        Index("messages_created_idx", created_at.desc()),
    )


class File(Base):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_key: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column()
    height: Mapped[int | None] = mapped_column()
    duration_ms: Mapped[int | None] = mapped_column()
    av_status: Mapped[str] = mapped_column(String(16), default="skip", nullable=False)
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (Index("files_owner_idx", "owner_id"),)


class MessageAttachment(Base):
    __tablename__ = "message_attachments"

    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    message_seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id"), primary_key=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["chat_id", "message_seq"],
            ["messages.chat_id", "messages.seq"],
            name="fk_message_attachments_message",
            ondelete="CASCADE",
        ),
        Index("message_attachments_file_idx", "file_id"),
    )


class MessageMention(Base):
    __tablename__ = "message_mentions"

    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    message_seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    mentioned_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        ForeignKeyConstraint(
            ["chat_id", "message_seq"],
            ["messages.chat_id", "messages.seq"],
            name="fk_message_mentions_message",
            ondelete="CASCADE",
        ),
        Index("message_mentions_user_idx", "mentioned_user_id", "chat_id"),
    )


class MessageReaction(Base):
    __tablename__ = "message_reactions"

    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    message_seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    emoji: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        ForeignKeyConstraint(
            ["chat_id", "message_seq"],
            ["messages.chat_id", "messages.seq"],
            name="fk_message_reactions_message",
            ondelete="CASCADE",
        ),
    )


class Bot(Base):
    __tablename__ = "bots"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    webhook_url: Mapped[str | None] = mapped_column(Text)
    webhook_secret_ref: Mapped[str | None] = mapped_column(String(128))
    is_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class BotToken(Base):
    __tablename__ = "bot_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.user_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    scopes: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()


class BotSubscription(Base):
    __tablename__ = "bot_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.user_id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    chat_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        Index(
            "bot_subscriptions_uq",
            "bot_id",
            "event_type",
            func.coalesce(chat_id, text(f"'{ZERO_UUID}'::uuid")),
            unique=True,
        ),
    )


class BotCommand(Base):
    __tablename__ = "bot_commands"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.user_id", ondelete="CASCADE"), primary_key=True
    )
    command: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    seq: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), primary_key=True
    )
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    chat_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _ts()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("outbox_unpublished_idx", "created_at", postgresql_where=text("published_at IS NULL")),
        Index("outbox_chat_seq_idx", "chat_id", "seq"),
    )


class LoginEvent(Base):
    __tablename__ = "login_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    origin: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (Index("login_events_user_idx", "user_id", created_at.desc()),)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (
        Index("audit_logs_time_idx", created_at.desc()),
        Index("audit_logs_entity_idx", "entity_type", "entity_id"),
    )
