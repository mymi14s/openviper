import datetime

import pytest
from jose import jwt

from openviper.auth.jwt import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)
from openviper.conf import settings
from openviper.exceptions import AuthenticationFailed, TokenExpired


def test_create_decode_access_token():
    user_id = 123
    token = create_access_token(user_id, extra_claims={"role": "admin"})

    payload = decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "admin"
    assert payload["type"] == "access"
    assert "exp" in payload
    assert "iat" in payload


def test_create_decode_refresh_token():
    user_id = "user-abc"
    token = create_refresh_token(user_id)

    payload = decode_refresh_token(token)
    assert payload["sub"] == user_id
    assert payload["type"] == "refresh"


def test_decode_invalid_token():
    with pytest.raises(AuthenticationFailed, match="Invalid token"):
        decode_access_token("invalid-token")


def test_decode_wrong_type():
    token = create_refresh_token(123)
    with pytest.raises(AuthenticationFailed, match="Invalid token type"):
        decode_access_token(token)

    token = create_access_token(123)
    with pytest.raises(AuthenticationFailed, match="Invalid token type"):
        decode_refresh_token(token)


def test_token_expired():
    # Build an already-expired token directly — no settings mutation needed.
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": str(123),
        "type": "access",
        "exp": now - datetime.timedelta(seconds=10),
        "iat": now - datetime.timedelta(seconds=20),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(TokenExpired):
        decode_access_token(token)


def test_refresh_token_expired():
    """decode_refresh_token raises TokenExpired for an expired refresh token."""
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": str(99),
        "type": "refresh",
        "exp": now - datetime.timedelta(seconds=10),
        "iat": now - datetime.timedelta(seconds=20),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(TokenExpired):
        decode_refresh_token(token)
