import asyncio
import re

import httpx

from app.config import get_settings


async def main() -> int:
    settings = get_settings()
    base = settings.public_base_url
    jar: dict[str, str] = {}

    async def collect(response: httpx.Response) -> None:
        for name, value in response.headers.multi_items():
            if name.lower() != "set-cookie":
                continue
            part = value.split(";", 1)[0]
            cookie_name, _, val = part.partition("=")
            jar[cookie_name.strip()] = val.strip()

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=30, event_hooks={"response": [collect]}
    ) as http:
        r = await http.get(f"{base}/v1/auth/login")
        cookie_header = "; ".join(f"{k}={v}" for k, v in jar.items())
        action = re.search(r'action="([^"]+)"', r.text).group(1).replace("&amp;", "&")
        r2 = await http.post(
            action,
            data={"username": "testtoken", "password": "TestToken1234!", "credentialId": "", "login": "Sign In"},
            headers={"Cookie": cookie_header},
        )
        print(f"final: {r2.status_code} url={r2.request.url}")
        if r2.status_code >= 400:
            print("body:", r2.text[:300])
        cookie_header = "; ".join(f"{k}={v}" for k, v in jar.items())
        sid = "vibe_session" in jar
        csrf = jar.get("vibe_csrf")
        print(f"session cookie: {sid}, csrf: {bool(csrf)}")
        if not sid:
            return 1
        me = await http.get(f"{base}/v1/me", headers={"Cookie": cookie_header, "X-CSRF-Token": csrf or ""})
        print(f"/v1/me: {me.status_code} {me.json()}")
        chats = await http.get(f"{base}/v1/chats", headers={"Cookie": cookie_header, "X-CSRF-Token": csrf or ""})
        print(f"/v1/chats: {chats.status_code} {chats.json()}")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
