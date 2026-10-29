from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PushDecision:
    push: bool
    reason: str


def should_push(
    *,
    is_sender: bool,
    mode: str,
    mentioned: bool,
    mentions_all: bool,
    muted_until: datetime | None,
    dnd_until: datetime | None,
    online: bool,
    now: datetime,
) -> PushDecision:
    if is_sender:
        return PushDecision(False, "sender")
    if mode == "none":
        return PushDecision(False, "mode_none")
    if muted_until is not None and muted_until > now:
        return PushDecision(False, "muted")
    if dnd_until is not None and dnd_until > now:
        return PushDecision(False, "dnd")
    if mode == "mentions" and not (mentioned or mentions_all):
        return PushDecision(False, "mentions_only")
    if online:
        return PushDecision(False, "online")
    return PushDecision(True, "ok")
