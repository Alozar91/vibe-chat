import logging

from app.config import get_settings
from app.core.timeutil import utcnow
from app.models import User, UserStatus
from app.modules.auth.keycloak import KeycloakAdmin

logger = logging.getLogger("vibe.sync")


async def sync_users_from_keycloak() -> None:
    settings = get_settings()
    _ = settings
    admin = KeycloakAdmin()
    from app.db.session import session_factory

    kc_users: dict[str, dict] = {}
    first = 0
    while True:
        page = await admin.list_users(first=first, max_results=500)
        if not page:
            break
        for item in page:
            kc_users[item["id"]] = item
        if len(page) < 500:
            break
        first += 500

    from sqlalchemy import select

    async with session_factory() as session:
        locals_rows = (
            await session.scalars(
                select(User).where(User.kind == "human", User.is_deleted.is_(False))
            )
        ).all()
        by_sub = {u.keycloak_sub: u for u in locals_rows if u.keycloak_sub}
        missing = [sub for sub in kc_users if sub not in by_sub]
        created = 0
        for sub in missing:
            info = kc_users[sub]
            username = info.get("username") or sub[:12]
            existing = (
                await session.scalars(select(User).where(User.username == username))
            ).one_or_none()
            if existing is not None:
                if existing.keycloak_sub is None:
                    existing.keycloak_sub = sub
                    existing.source = "ldap"
            else:
                first_name = info.get("firstName", "")
                last_name = info.get("lastName", "")
                session.add(
                    User(
                        kind="human",
                        keycloak_sub=sub,
                        username=username,
                        full_name=f"{first_name} {last_name}".strip() or username,
                        email=info.get("email"),
                        status=UserStatus.ACTIVE if info.get("enabled", True) else UserStatus.DISABLED,
                        source="ldap",
                    )
                )
                created += 1
        updated = 0
        for sub, user in by_sub.items():
            kc_info = kc_users.get(sub)
            if kc_info is None:
                if user.status != UserStatus.DISABLED:
                    user.status = UserStatus.DISABLED
                    user.updated_at = utcnow()
                    updated += 1
                continue
            enabled = kc_info.get("enabled", True)
            desired = UserStatus.ACTIVE if enabled else UserStatus.DISABLED
            if user.status != desired:
                user.status = desired
                user.updated_at = utcnow()
                updated += 1
        await session.commit()
    logger.info("Keycloak sync: создано %s, обновлено %s", created, updated)
