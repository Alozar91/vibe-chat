import uuid

from app.core import permissions
from app.core.ids import uuid7
from app.core.mentions import parse_mentions
from app.core.notifications_rules import should_push
from app.core.security import generate_invite_code, sha256_hex
from app.core.timeutil import utcnow


class TestPermissions:
    def test_org_roles(self):
        assert permissions.is_org_admin("owner")
        assert permissions.is_org_admin("admin")
        assert not permissions.is_org_admin("member")

    def test_chat_roles(self):
        assert permissions.can_delete_chat("owner")
        assert not permissions.can_delete_chat("admin")
        assert permissions.can_delete_other_message("admin")
        assert not permissions.can_delete_other_message("member")
        assert permissions.can_manage_bots_in_chat("owner")
        assert not permissions.can_manage_bots_in_chat("member")

    def test_add_members_depends_on_settings(self):
        assert permissions.can_add_members("admin", {})
        assert permissions.can_add_members("member", {"who_can_add_members": "all"})
        assert not permissions.can_add_members("member", {"who_can_add_members": "admins"})

    def test_mentions_all_threshold(self):
        assert permissions.mentions_all_allowed("member", 99, 100)
        assert not permissions.mentions_all_allowed("member", 100, 100)
        assert permissions.mentions_all_allowed("admin", 500, 100)


class TestMentions:
    def test_parse_basic(self):
        uid = uuid.uuid4()
        uid2 = uuid.uuid4()
        members = {"ivanov": uid, "petrov": uid2}
        mentions, mentions_all = parse_mentions(
            "Привет @ivanov и @petrov, @unknown пропущен", members, permissions.ChatRole.MEMBER, 10, 100
        )
        assert mentions == [uid, uid2]
        assert not mentions_all

    def test_parse_all_allowed_small_chat(self):
        members = {"ivanov": uuid.uuid4()}
        mentions, mentions_all = parse_mentions(
            "@all проверьте", members, permissions.ChatRole.MEMBER, 10, 100
        )
        assert mentions_all
        assert mentions == []

    def test_parse_all_denied_big_chat(self):
        members = {"ivanov": uuid.uuid4()}
        mentions, mentions_all = parse_mentions(
            "@all привет", members, permissions.ChatRole.MEMBER, 500, 100
        )
        assert not mentions_all
        assert permissions.mentions_all_allowed("admin", 500, 100)
        _, mentions_all_admin = parse_mentions(
            "@all привет", members, permissions.ChatRole.ADMIN, 500, 100
        )
        assert mentions_all_admin


class TestPushRules:
    NOW = utcnow()

    def test_sender_no_push(self):
        decision = should_push(
            is_sender=True, mode="all", mentioned=False, mentions_all=False,
            muted_until=None, dnd_until=None, online=False, now=self.NOW,
        )
        assert not decision.push

    def test_mentions_only_mode(self):
        base = {
            "is_sender": False, "mode": "mentions", "muted_until": None,
            "dnd_until": None, "online": False, "now": self.NOW,
        }
        assert should_push(mentioned=True, mentions_all=False, **base).push
        assert should_push(mentioned=False, mentions_all=True, **base).push
        assert not should_push(mentioned=False, mentions_all=False, **base).push

    def test_mute_and_dnd(self):
        from datetime import timedelta

        future = self.NOW + timedelta(hours=1)
        base = {
            "is_sender": False, "mode": "all", "mentioned": False,
            "mentions_all": False, "online": False, "now": self.NOW,
        }
        assert not should_push(muted_until=future, dnd_until=None, **base).push
        assert not should_push(muted_until=None, dnd_until=future, **base).push
        past = self.NOW - timedelta(hours=1)
        assert should_push(muted_until=past, dnd_until=None, **base).push

    def test_none_mode(self):
        decision = should_push(
            is_sender=False, mode="none", mentioned=True, mentions_all=False,
            muted_until=None, dnd_until=None, online=False, now=self.NOW,
        )
        assert not decision.push


class TestUuid7:
    def test_shape(self):
        u = uuid7()
        assert u.version == 7
        assert u.variant == uuid.RFC_4122

    def test_uniqueness(self):
        assert len({uuid7() for _ in range(1000)}) == 1000

    def test_time_ordered(self):
        import time as time_mod

        a = uuid7()
        time_mod.sleep(0.003)
        assert a.int < uuid7().int


class TestTokens:
    def test_invite_code_128bit(self):
        import base64

        code = generate_invite_code()
        assert 20 <= len(code) <= 24
        raw = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
        assert len(raw) == 16

    def test_bot_token_shape_and_hash(self):
        from app.core.security import generate_bot_token

        token = generate_bot_token()
        assert token.startswith("mt_")
        assert sha256_hex(token) == sha256_hex(token)
        assert sha256_hex(token) != sha256_hex(token + "x")
