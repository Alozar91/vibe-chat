"""Проверка настроек: значения по умолчанию и override через APP_ env."""

import pytest
from app.core.config import Settings


def test_defaults() -> None:
    s = Settings()
    assert s.keycloak_realm == "vibe-chat"
    assert s.keycloak_audience == "backend-api"
    assert s.silo_bucket == "vibe-files"
    assert s.presign_ttl_seconds == 3600


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_SILO_BUCKET", "other")
    s = Settings()
    assert s.silo_bucket == "other"
