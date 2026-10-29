import argparse
import asyncio
import sys

from sqlalchemy import select


async def bootstrap_admin(username: str) -> int:
    from app.config import get_settings
    from app.core.audit import log_action
    from app.core.timeutil import utcnow
    from app.db.session import init_engine, session_factory
    from app.models import User, UserRole

    init_engine()
    settings = get_settings()
    username = (username or settings.bootstrap_admin_username).strip()
    if not username:
        print("Укажите BOOTSTRAP_ADMIN_USERNAME в .env или аргументом")
        return 1
    async with session_factory() as session:
        user = (
            await session.scalars(select(User).where(User.username == username))
        ).one_or_none()
        if user is None:
            print(f"Пользователь '{username}' не найден. Пусть войдёт один раз (JIT), затем повторите.")
            return 1
        user.role = UserRole.OWNER
        user.updated_at = utcnow()
        await log_action(session, actor_id=user.id, action="user.promoted_owner", entity_type="user", entity_id=str(user.id))
        await session.commit()
        print(f"OK: {username} теперь owner")
    return 0


async def ensure_bucket() -> int:
    from app.modules.media.service import ensure_bucket

    await asyncio.to_thread(ensure_bucket)
    print("OK: bucket готов")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub_boot = sub.add_parser("bootstrap-admin")
    sub_boot.add_argument("username", nargs="?", default="")
    sub.add_parser("ensure-bucket")
    args = parser.parse_args(argv)
    if args.command == "bootstrap-admin":
        return asyncio.run(bootstrap_admin(args.username))
    if args.command == "ensure-bucket":
        return asyncio.run(ensure_bucket())
    return 1


if __name__ == "__main__":
    sys.exit(main())
