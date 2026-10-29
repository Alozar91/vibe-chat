import base64
import json
import sys

import httpx

from app.config import get_settings
from app.core.security import verify_access_token


async def main() -> int:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15) as http:
        admin = (await http.post(
            f"{settings.keycloak_url}/realms/master/protocol/openid-connect/token",
            data={"grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": "admin"},
        )).json()["access_token"]
        headers = {"Authorization": f"Bearer {admin}"}
        client = (await http.get(
            f"{settings.keycloak_url}/admin/realms/messenger/clients?clientId=messenger-mobile", headers=headers
        )).json()[0]
        client["directAccessGrantsEnabled"] = True
        await http.put(
            f"{settings.keycloak_url}/admin/realms/messenger/clients/{client['id']}",
            headers=headers, json=client,
        )
        try:
            token = (await http.post(
                f"{settings.keycloak_url}/realms/messenger/protocol/openid-connect/token",
                data={
                    "grant_type": "password", "client_id": "messenger-mobile",
                    "username": "testtoken", "password": "TestToken1234!", "scope": "openid",
                },
            )).json()
            if "access_token" not in token:
                print(f"TOKEN ERROR: {token}")
                return 1
            claims = await verify_access_token(token["access_token"])
            part = token["access_token"].split(".")[1]
            part += "=" * (-len(part) % 4)
            payload = json.loads(base64.urlsafe_b64decode(part))
            print(
                f"verify_access_token OK: sub={claims['sub']} "
                f"aud={payload.get('aud')} preferred={payload.get('preferred_username')}"
            )
            userinfo = (await http.get(
                f"{settings.keycloak_url}/realms/messenger/protocol/openid-connect/userinfo",
                headers={"Authorization": f"Bearer {token['access_token']}"},
            )).json()
            print(f"userinfo OK: {userinfo.get('preferred_username')}, email={userinfo.get('email')}")
            return 0
        finally:
            client["directAccessGrantsEnabled"] = False
            await http.put(
                f"{settings.keycloak_url}/admin/realms/messenger/clients/{client['id']}",
                headers=headers, json=client,
            )


if __name__ == "__main__":
    _ = sys
    import asyncio

    raise SystemExit(asyncio.run(main()))
