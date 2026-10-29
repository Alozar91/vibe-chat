import re
import uuid

from app.core import permissions
from app.core.permissions import ChatRole

MENTION_RE = re.compile(r"@([A-Za-z0-9_.-]{1,64})")


def parse_mentions(
    body: str,
    member_usernames: dict[str, uuid.UUID],
    chat_role: ChatRole,
    members_count: int,
    all_threshold: int,
) -> tuple[list[uuid.UUID], bool]:
    mentioned: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    mentions_all = False
    for match in MENTION_RE.finditer(body):
        token = match.group(1).lower()
        if token == "all":
            if permissions.mentions_all_allowed(chat_role, members_count, all_threshold):
                mentions_all = True
            continue
        user_id = member_usernames.get(token)
        if user_id is not None and user_id not in seen:
            seen.add(user_id)
            mentioned.append(user_id)
    return mentioned, mentions_all
