from enum import StrEnum


class OrgRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class ChatRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


def is_org_admin(role: OrgRole | str) -> bool:
    return role in (OrgRole.OWNER, OrgRole.ADMIN)


def is_chat_admin(role: ChatRole | str) -> bool:
    return role in (ChatRole.OWNER, ChatRole.ADMIN)


def can_edit_chat(role: ChatRole | str) -> bool:
    return is_chat_admin(role)


def can_delete_chat(role: ChatRole | str) -> bool:
    return role == ChatRole.OWNER


def can_add_members(role: ChatRole | str, chat_settings: dict) -> bool:
    who = (chat_settings or {}).get("who_can_add_members", "admins")
    if who == "all":
        return True
    return is_chat_admin(role)


def can_remove_members(role: ChatRole | str) -> bool:
    return is_chat_admin(role)


def can_manage_bots_in_chat(role: ChatRole | str) -> bool:
    return is_chat_admin(role)


def can_create_invite(role: ChatRole | str) -> bool:
    return is_chat_admin(role)


def can_delete_other_message(role: ChatRole | str) -> bool:
    return is_chat_admin(role)


def can_manage_bots_org(role: OrgRole | str) -> bool:
    return is_org_admin(role)


def can_manage_users_org(role: OrgRole | str) -> bool:
    return is_org_admin(role)


def can_edit_org_settings(role: OrgRole | str) -> bool:
    return is_org_admin(role)


def mentions_all_allowed(chat_role: ChatRole | str, members_count: int, threshold: int) -> bool:
    if members_count < threshold:
        return True
    return is_chat_admin(chat_role)
