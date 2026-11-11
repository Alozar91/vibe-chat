"""Тесты JWT-валидации (§5): подделка/экспирация/iss/aud → 401; валидный — проходит."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from app.core.security import validate_jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

# Тестовая RSA-пара (генерируется один раз на модуль)
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "test-key-1"


def _make_token(**overrides: Any) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": "test-sub-123",
        "preferred_username": "alice",
        "iss": "http://localhost:8080/realms/vibe-chat",
        "aud": "backend-api",
        "exp": now + timedelta(minutes=5),
        "iat": now,
    }
    claims.update(overrides)
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256", headers={"kid": _KID})


def _validate_with_mocked_jwks(token: str) -> dict[str, Any]:
    with patch("app.core.security._jwks_client") as mock_client:
        mock_client.get_signing_key_from_jwt.return_value.key = _PRIVATE_KEY.public_key()
        return validate_jwt(token)


def test_valid_token_passes() -> None:
    claims = _validate_with_mocked_jwks(_make_token())
    assert claims["sub"] == "test-sub-123"


def test_expired_token_rejected() -> None:
    token = _make_token(exp=datetime.now(UTC) - timedelta(minutes=1))
    with pytest.raises(HTTPException) as exc:
        _validate_with_mocked_jwks(token)
    assert exc.value.status_code == 401


def test_wrong_audience_rejected() -> None:
    token = _make_token(aud="other-api")
    with pytest.raises(HTTPException) as exc:
        _validate_with_mocked_jwks(token)
    assert exc.value.status_code == 401


def test_wrong_issuer_rejected() -> None:
    token = _make_token(iss="https://evil.example/realms/vibe-chat")
    with pytest.raises(HTTPException) as exc:
        _validate_with_mocked_jwks(token)
    assert exc.value.status_code == 401


def test_bad_signature_rejected() -> None:
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {
            "sub": "x",
            "iss": "http://localhost:8080/realms/vibe-chat",
            "aud": "backend-api",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        other_key,
        algorithm="RS256",
        headers={"kid": _KID},
    )
    with pytest.raises(HTTPException) as exc:
        _validate_with_mocked_jwks(token)
    assert exc.value.status_code == 401


def test_missing_sub_rejected() -> None:
    token = _make_token(sub=None)
    with pytest.raises(HTTPException) as exc:
        _validate_with_mocked_jwks(token)
    assert exc.value.status_code == 401
