"""Тесты server selection (концепция §19): /server/info, фейс-контроль, rate-limit."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from app.core.config import Settings
from app.main import app
from app.services import server_info as si
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_rl() -> Iterator[None]:
    si.reset_join_rate_limit()
    yield
    si.reset_join_rate_limit()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_server_info_no_code(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Без APP_JOIN_CODE профиль отдаётся без заголовков (§19.5 opt-in)."""
    s = Settings(
        server_name="Тест",
        keycloak_url="https://x.example/kc",
        push_driver="off",
        min_app_version="1.0.0",
        latest_app_version="1.2.0",
        app_download_url="https://x.example/app.apk",
        _env_file=None,
    )
    monkeypatch.setattr(si, "get_settings", lambda: s)
    r = client.get("/api/v1/server/info")
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "Тест"
    assert d["kc_url"] == "https://x.example/kc"
    assert d["realm"] == "vibe-chat"
    assert d["push"] == {"driver": "off", "firebase": None}
    assert d["min_version"] == "1.0.0"
    assert d["app_download_url"] == "https://x.example/app.apk"


def test_public_keycloak_url_override(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """APP_PUBLIC_KEYCLOAK_URL перекрывает kc_url в профиле (NAT/dev), issuer — нет."""
    s = Settings(
        keycloak_url="http://localhost:8080",
        public_keycloak_url="http://10.0.2.2:8080",
        _env_file=None,
    )
    monkeypatch.setattr(si, "get_settings", lambda: s)
    r = client.get("/api/v1/server/info")
    assert r.status_code == 200
    assert r.json()["kc_url"] == "http://10.0.2.2:8080"


def test_join_code_required_and_accepted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """С кодом: без заголовка 403 join_code_required, с верным — 200 (§19.5)."""
    s = Settings(server_name="X", join_code="s3cret", push_driver="off", _env_file=None)
    monkeypatch.setattr(si, "get_settings", lambda: s)
    r = client.get("/api/v1/server/info")
    assert r.status_code == 403
    assert r.json()["detail"] == "join_code_required"
    # неверный код — та же ошибка (не даём оракул «код нужен» vs «код неверен»)
    r = client.get("/api/v1/server/info", headers={"X-Vibe-Join": "wrong"})
    assert r.status_code == 403
    assert r.json()["detail"] == "join_code_required"
    # верный код
    r = client.get("/api/v1/server/info", headers={"X-Vibe-Join": "s3cret"})
    assert r.status_code == 200
    assert r.json()["name"] == "X"


def test_join_rate_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """>10 неуспешных за окно → 429 (§19.5)."""
    s = Settings(join_code="s3cret", _env_file=None)
    monkeypatch.setattr(si, "get_settings", lambda: s)
    for _ in range(10):
        r = client.get("/api/v1/server/info", headers={"X-Vibe-Join": "nope"})
        assert r.status_code == 403
    r = client.get("/api/v1/server/info", headers={"X-Vibe-Join": "nope"})
    assert r.status_code == 429
    # даже верный код в блоке — 429 (блок снимается только по окну)
    r = client.get("/api/v1/server/info", headers={"X-Vibe-Join": "s3cret"})
    assert r.status_code == 429


def test_register_and_version_gated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Фейс-контроль покрывает /auth/register и /app/version (§19.5)."""
    s = Settings(join_code="s3cret", _env_file=None)
    monkeypatch.setattr(si, "get_settings", lambda: s)
    r = client.get("/api/v1/app/version")
    assert r.status_code == 403
    assert r.json()["detail"] == "join_code_required"
    r = client.post("/api/v1/auth/register", json={})
    assert r.status_code == 403
    r = client.get("/api/v1/app/version", headers={"X-Vibe-Join": "s3cret"})
    assert r.status_code == 200  # сами поля версии — test_push.py


def test_firebase_config_parsing(tmp_path: Any) -> None:
    """google-services.json → поля клиента по package_name (§19.6)."""
    cfg = {
        "project_info": {
            "project_number": "777",
            "project_id": "host-fb",
            "storage_bucket": "host-fb.appspot.com",
        },
        "client": [
            {
                "client_info": {
                    "mobilesdk_app_id": "1:777:android:aaa",
                    "android_client_info": {"package_name": "com.other.app"},
                },
                "api_key": [{"current_key": "k0"}],
            },
            {
                "client_info": {
                    "mobilesdk_app_id": "1:777:android:bbb",
                    "android_client_info": {"package_name": "ru.vibe.chat.app"},
                },
                "api_key": [{"current_key": "k1"}],
            },
        ],
    }
    p = tmp_path / "gs.json"
    p.write_text(json.dumps(cfg))
    assert si.parse_firebase_client_config(str(p)) == {
        "project_id": "host-fb",
        "sender_id": "777",
        "storage_bucket": "host-fb.appspot.com",
        "app_id": "1:777:android:bbb",
        "api_key": "k1",
    }
    # без файла / битый json — None (discovery не падает)
    assert si.parse_firebase_client_config("") is None
    assert si.parse_firebase_client_config(str(tmp_path / "nope.json")) is None
    p.write_text("{broken")
    assert si.parse_firebase_client_config(str(p)) is None


def test_push_fcm_with_firebase(
    client: TestClient, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """driver=fcm + конфиг → push.firebase в профиле (§19.6)."""
    cfg = {
        "project_info": {"project_number": "1", "project_id": "p", "storage_bucket": "b"},
        "client": [
            {
                "client_info": {
                    "mobilesdk_app_id": "a",
                    "android_client_info": {"package_name": "ru.vibe.chat.app"},
                },
                "api_key": [{"current_key": "k"}],
            }
        ],
    }
    f = tmp_path / "gs.json"
    f.write_text(json.dumps(cfg))
    s = Settings(
        push_driver="fcm",
        firebase_config_path=str(f),
        fcm_project_id="p",
        _env_file=None,
    )
    monkeypatch.setattr(si, "get_settings", lambda: s)
    d = client.get("/api/v1/server/info").json()
    assert d["push"] == {
        "driver": "fcm",
        "firebase": {
            "project_id": "p",
            "sender_id": "1",
            "storage_bucket": "b",
            "app_id": "a",
            "api_key": "k",
        },
    }
