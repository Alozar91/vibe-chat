"""Seed-команда: платформенный админ + первый инвайт (§5, §12 концепции).

Запускается в контейнере backend после `alembic upgrade head`:
    python -m app.scripts.seed_admin

На чистой БД создаёт:
  - платформенного админа (KC-аккаунт через Admin API — только username+password,
    персональные данные в PostgreSQL, §5);
  - первый инвайт-код (multi-use, безлимит) — им регистрируются остальные.
"""

import asyncio
import os
import uuid

import httpx
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.invite import Invite
from app.models.user import User
from app.services.invites import generate_invite_code, hash_invite_code
from app.services.keycloak_admin import get_kc_admin
from sqlalchemy import select

SEED_USERNAME = os.environ.get("SEED_ADMIN_USERNAME", "admin")
SEED_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD", "")


async def _find_kc_user_id(username: str) -> str | None:
    """Поиск пользователя в KC Admin API (восстановление частичного seed)."""
    s = get_settings()
    base = s.keycloak_url.rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        token_resp = await client.post(
            f"{base}/realms/{s.keycloak_realm}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": s.keycloak_admin_client_id,
                "client_secret": s.keycloak_admin_client_secret,
            },
        )
        if token_resp.status_code != 200:
            raise SystemExit(f"KC admin token failed: {token_resp.status_code}")
        headers = {"Authorization": f"Bearer {token_resp.json()['access_token']}"}
        search = await client.get(
            f"{base}/admin/realms/{s.keycloak_realm}/users",
            headers=headers,
            params={"username": username, "exact": "true"},
        )
        if search.status_code != 200:
            raise SystemExit(f"KC user search failed: {search.status_code}")
        users = search.json()
        return users[0]["id"] if users else None


async def _ensure_kc_user(username: str, password: str) -> str:
    """KC id пользователя: создаёт; 409 (уже есть с прошлого раза) → ищет id."""
    try:
        return await get_kc_admin().create_user(username=username, password=password)
    except Exception as exc:  # noqa: BLE001 — скрипт: любой сбой → диагностика
        found = await _find_kc_user_id(username)
        if found is None:
            raise SystemExit(f"KC: не удалось создать пользователя: {exc}") from exc
        print("KC-пользователь уже существует — переиспользую")
        return found


async def main() -> None:
    if not SEED_PASSWORD:
        raise SystemExit("Задайте SEED_ADMIN_PASSWORD (env) — пароль платформенного админа")
    if not get_settings().keycloak_admin_client_secret:
        raise SystemExit("APP_KEYCLOAK_ADMIN_CLIENT_SECRET не настроен (§5, §12)")

    print(f"Seed: админ '{SEED_USERNAME}' + первый инвайт")
    kc_id = await _ensure_kc_user(SEED_USERNAME, SEED_PASSWORD)

    async with SessionLocal() as db:
        # Пользователь: уже есть (повторный запуск) → только обновить sub
        user = await db.scalar(select(User).where(User.username == SEED_USERNAME))
        if user is None:
            user = User(
                id=str(uuid.uuid4()),
                keycloak_sub=kc_id,
                username=SEED_USERNAME,
                display_name=SEED_USERNAME,
                is_platform_admin=True,  # только seed: регистрация даёт false (§5)
                is_active=True,
            )
            db.add(user)
            await db.flush()
            print(f"  пользователь создан (БД id={user.id})")
        elif user.keycloak_sub is None:
            user.keycloak_sub = kc_id
            await db.flush()
            print("  пользователь уже был в БД — привязан keycloak_sub")
        else:
            # KC без своей БД (dev-file): пересоздание контейнера = новые KC-id;
            # перепривязываем sub, иначе логин сломается молча
            if user.keycloak_sub != kc_id:
                user.keycloak_sub = kc_id
                await db.commit()
                print("  keycloak_sub перепривязан (KC-контейнер пересоздавался)")
            else:
                print("  пользователь уже был в БД — OK")

        # Первый инвайт: если ещё нет ни одного действующего
        active = await db.scalar(select(Invite).where(Invite.deactivated_at.is_(None)))
        if active is None:
            code = generate_invite_code()
            db.add(
                Invite(
                    id=str(uuid.uuid4()),
                    code_hash=hash_invite_code(code),
                    created_by=user.id,
                    max_uses=None,
                    uses_count=0,
                )
            )
            await db.commit()
            print(f"  инвайт-код (сохраните): {code}")
        else:
            print("  действующий инвайт уже есть — новый не создаётся")


if __name__ == "__main__":
    asyncio.run(main())
