import logging
from typing import Any, Protocol

logger = logging.getLogger("vibe.push")


class Pusher(Protocol):
    async def send(
        self,
        *,
        platform: str,
        token: str | None,
        webpush_endpoint: str | None,
        webpush_keys: dict | None,
        title: str,
        body: str,
        sender_id: str,
    ) -> None: ...


class LogPusher:
    async def send(
        self,
        *,
        platform: str,
        token: str | None,
        webpush_endpoint: str | None,
        webpush_keys: dict | None,
        title: str,
        body: str,
        sender_id: str,
    ) -> None:
        logger.info("push (log) -> %s %s: %s", platform, token or webpush_endpoint, body[:80])


class WebPusher:
    def __init__(self, vapid_private: str, vapid_public: str, subject: str) -> None:
        self.vapid_private = vapid_private
        self.vapid_public = vapid_public
        self.subject = subject

    async def send(
        self,
        *,
        platform: str,
        token: str | None,
        webpush_endpoint: str | None,
        webpush_keys: dict | None,
        title: str,
        body: str,
        sender_id: str,
    ) -> None:
        if platform != "web" or not webpush_endpoint:
            return
        import asyncio
        import json

        from pywebpush import webpush

        payload = json.dumps({"title": title, "body": body, "sender_id": sender_id})

        def _send() -> None:
            webpush(
                subscription_info={"endpoint": webpush_endpoint, "keys": webpush_keys or {}},
                data=payload,
                vapid_private_key=self.vapid_private,
                vapid_public_key=self.vapid_public,
            )

        await asyncio.to_thread(_send)


class FcmPusher:
    def __init__(self, credentials_path: str) -> None:
        self.credentials_path = credentials_path
        self._initialized = False

    def _init(self) -> None:
        if self._initialized:
            return
        import firebase_admin
        from firebase_admin import credentials

        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(self.credentials_path))
        self._initialized = True

    async def send(
        self,
        *,
        platform: str,
        token: str | None,
        webpush_endpoint: str | None,
        webpush_keys: dict | None,
        title: str,
        body: str,
        sender_id: str,
    ) -> None:
        if platform != "android" or not token:
            return
        import asyncio

        def _send() -> None:
            self._init()
            from firebase_admin import messaging

            messaging.send(
                messaging.Message(
                    token=token,
                    notification=messaging.Notification(title=title, body=body),
                    data={"sender_id": sender_id},
                )
            )

        await asyncio.to_thread(_send)


class ApnsPusher:
    def __init__(self, key_path: str, key_id: str, team_id: str, topic: str) -> None:
        self.key_path = key_path
        self.key_id = key_id
        self.team_id = team_id
        self.topic = topic

    async def send(
        self,
        *,
        platform: str,
        token: str | None,
        webpush_endpoint: str | None,
        webpush_keys: dict | None,
        title: str,
        body: str,
        sender_id: str,
    ) -> None:
        if platform != "ios" or not token:
            return
        from aioapns import APNs, NotificationRequest

        client = APNs(
            key=self.key_path,
            key_id=self.key_id,
            team_id=self.team_id,
            topic=self.topic,
        )
        request = NotificationRequest(
            device_token=token,
            message={"aps": {"alert": {"title": title, "body": body}, "sound": "default"}},
        )
        await client.send_notification(request)


_pusher: Pusher | None = None


def get_pusher() -> Pusher:
    global _pusher
    if _pusher is not None:
        return _pusher
    from app.config import get_settings

    settings = get_settings()
    pushers: list[Pusher] = []
    if settings.fcm_credentials_path:
        pushers.append(FcmPusher(settings.fcm_credentials_path))
    if settings.apns_key_path and settings.apns_key_id and settings.apns_team_id and settings.apns_topic:
        pushers.append(ApnsPusher(settings.apns_key_path, settings.apns_key_id, settings.apns_team_id, settings.apns_topic))
    if settings.vapid_private_key and settings.vapid_public_key:
        pushers.append(WebPusher(settings.vapid_private_key, settings.vapid_public_key, settings.webpush_subject))

    class MultiPusher:
        def __init__(self, items: list[Pusher], fallback: Pusher) -> None:
            self.items = items
            self.fallback = fallback

        async def send(self, **kwargs: Any) -> None:
            for item in self.items:
                await item.send(**kwargs)
                return
            await self.fallback.send(**kwargs)

    _pusher = MultiPusher(pushers, LogPusher())
    return _pusher
