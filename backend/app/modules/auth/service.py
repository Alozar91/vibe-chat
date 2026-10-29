import json
import secrets
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from valkey.asyncio import Valkey

from app.core.errors import unauthorized, upstream
from app.core.security import encode_state, verify_id_token
from app.core.timeutil import utcnow
from app.models import LoginEvent
from app.modules.auth import keycloak, sessions
from app.modules.auth.sessions import SESSION_PREFIX
from app.modules.users.service import provision_user_from_claims

STATE_PREFIX = "auth_state:"
STATE_TTL = 600


async def save_state(valkey: Valkey, state: str, nonce: str, origin: str) -> None:
    await valkey.set(
        STATE_PREFIX + state,
        json.dumps({"nonce": nonce, "origin": origin}),
        ex=STATE_TTL,
    )


async def pop_state(valkey: Valkey, state: str) -> dict[str, Any] | None:
    raw = await valkey.getdel(STATE_PREFIX + state)
    if raw is None:
        return None
    return json.loads(raw)


async def build_login_redirect(valkey: Valkey, origin: str) -> str:
    nonce = secrets.token_urlsafe(16)
    state = encode_state(nonce, origin)
    await save_state(valkey, state, nonce, origin)
    redirect_uri = f"{origin}/v1/auth/callback"
    return keycloak.build_authorize_url(redirect_uri, state, nonce)


async def complete_login(
    db: AsyncSession,
    valkey: Valkey,
    code: str,
    state: str,
    ip: str | None,
    user_agent: str | None,
) -> tuple[str, str, str]:
    record = await pop_state(valkey, state)
    if record is None:
        raise unauthorized("Истёк или недействителен state")
    origin = record["origin"]
    tokens = await keycloak.exchange_code(code, f"{origin}/v1/auth/callback")
    id_token = tokens.get("id_token")
    if not id_token:
        raise upstream("Keycloak не вернул id_token")
    claims = await verify_id_token(id_token)
    if claims.get("nonce") != record["nonce"]:
        raise unauthorized("nonce не совпал")
    user = await provision_user_from_claims(db, claims)
    db.add(
        LoginEvent(
            user_id=user.id,
            origin="password",
            status="success",
            ip=ip,
            user_agent=user_agent,
            created_at=utcnow(),
        )
    )
    sid, csrf = await sessions.create_session(valkey, user.id, "web", ip, user_agent, tokens)
    await db.commit()
    return sid, csrf, origin


async def direct_login(
    db: AsyncSession,
    valkey: Valkey,
    username: str,
    password: str,
    ip: str | None,
    user_agent: str | None,
) -> tuple[str, str, Any]:
    tokens = await keycloak.password_grant(username, password)
    id_token = tokens.get("id_token")
    if not id_token:
        raise upstream("Keycloak не вернул id_token")
    claims = await verify_id_token(id_token)
    user = await provision_user_from_claims(db, claims)
    db.add(
        LoginEvent(
            user_id=user.id,
            origin="password",
            status="success",
            ip=ip,
            user_agent=user_agent,
            created_at=utcnow(),
        )
    )
    sid, csrf = await sessions.create_session(valkey, user.id, "web", ip, user_agent, tokens)
    await db.commit()
    return sid, csrf, user


async def logout_current(valkey: Valkey, sid: str) -> None:
    raw = await valkey.get(SESSION_PREFIX + sid)
    if raw is None:
        return
    data = json.loads(raw)
    refresh = (data.get("tokens") or {}).get("refresh_token")
    if refresh:
        await keycloak.revoke_refresh_token(refresh)
    await sessions.revoke_session(valkey, sid)
