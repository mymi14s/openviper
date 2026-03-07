from unittest.mock import MagicMock, patch

import pytest

from openviper.auth.models import AnonymousUser
from openviper.exceptions import TokenExpired
from openviper.middleware.auth import _USER_CACHE, AuthenticationMiddleware


@pytest.fixture(autouse=True)
def clear_user_cache():
    """Ensure the TTL user cache is empty before and after each test."""
    _USER_CACHE.clear()
    yield
    _USER_CACHE.clear()


@pytest.mark.asyncio
async def test_auth_non_http():
    calls = []

    async def dummy_app(scope, receive, send):
        calls.append("app_bypassed")

    mw = AuthenticationMiddleware(dummy_app)
    scope = {"type": "lifespan"}
    await mw(scope, None, None)

    assert calls == ["app_bypassed"]
    assert "user" not in scope


@pytest.mark.asyncio
async def test_auth_no_credentials():
    async def dummy_app(scope, receive, send):
        pass

    mw = AuthenticationMiddleware(dummy_app)

    scope = {"type": "http", "headers": []}
    await mw(scope, None, None)

    assert isinstance(scope["user"], AnonymousUser)
    assert scope["auth"] == {"type": "none"}


@pytest.mark.asyncio
@patch("openviper.middleware.auth.decode_access_token")
@patch("openviper.middleware.auth.get_user_by_id")
async def test_auth_jwt_valid(mock_get_user, mock_decode):
    mock_decode.return_value = {"sub": "10"}
    mock_user = MagicMock()
    mock_user.is_active = True
    mock_get_user.return_value = mock_user

    async def dummy_app(scope, receive, send):
        pass

    mw = AuthenticationMiddleware(dummy_app)

    scope = {"type": "http", "headers": [(b"authorization", b"Bearer mycooltoken")]}
    await mw(scope, None, None)

    assert scope["user"] is mock_user
    assert scope["auth"] == {"type": "jwt", "token": "mycooltoken"}
    mock_decode.assert_called_once_with("mycooltoken")
    mock_get_user.assert_called_once_with(10)


@pytest.mark.asyncio
@patch("openviper.middleware.auth.decode_access_token")
async def test_auth_jwt_invalid(mock_decode):
    mock_decode.side_effect = Exception("bad token")

    async def dummy_app(scope, receive, send):
        pass

    mw = AuthenticationMiddleware(dummy_app)

    scope = {"type": "http", "headers": [(b"authorization", b"Bearer badtoken")]}
    await mw(scope, None, None)

    assert isinstance(scope["user"], AnonymousUser)
    assert scope["auth"] == {"type": "none"}


@pytest.mark.asyncio
@patch("openviper.middleware.auth.get_user_from_session")
async def test_auth_session_valid(mock_session):
    mock_user = MagicMock()
    mock_session.return_value = mock_user

    async def dummy_app(scope, receive, send):
        pass

    mw = AuthenticationMiddleware(dummy_app)

    scope = {"type": "http", "headers": [(b"cookie", b"session=123")]}
    await mw(scope, None, None)

    assert scope["user"] is mock_user
    assert scope["auth"] == {"type": "session"}
    mock_session.assert_called_once_with("session=123")


@pytest.mark.asyncio
@patch("openviper.middleware.auth.decode_access_token")
@patch("openviper.middleware.auth.get_user_by_id")
async def test_auth_jwt_cache_hit(mock_get_user, mock_decode):
    """When a valid cache entry exists, get_user_by_id is NOT called."""
    import time

    mock_user = MagicMock()
    mock_user.is_active = True
    mock_decode.return_value = {"sub": "42"}

    # Pre-populate cache with a fresh entry
    _USER_CACHE[42] = (mock_user, time.monotonic() + 60.0)

    async def dummy_app(scope, receive, send):
        pass

    mw = AuthenticationMiddleware(dummy_app)
    scope = {"type": "http", "headers": [(b"authorization", b"Bearer sometoken")]}
    await mw(scope, None, None)

    assert scope["user"] is mock_user
    mock_get_user.assert_not_called()


# ── Cache eviction — expired entries first (lines 67-69) ─────────────────────


@pytest.mark.asyncio
@patch("openviper.middleware.auth.decode_access_token")
@patch("openviper.middleware.auth.get_user_by_id")
async def test_cache_eviction_expired_entries(mock_get_user, mock_decode):
    """When cache is full, expired entries are evicted before storing the new entry."""
    import time

    mock_decode.return_value = {"sub": "99"}
    new_user = MagicMock()
    new_user.is_active = True
    mock_get_user.return_value = new_user

    past = time.monotonic() - 1.0  # already expired

    # Fill cache to maxsize=2 with stale entries
    with patch("openviper.middleware.auth._USER_CACHE_MAXSIZE", 2):
        _USER_CACHE[1] = (MagicMock(), past)
        _USER_CACHE[2] = (MagicMock(), past)

        async def dummy_app(scope, receive, send):
            pass

        mw = AuthenticationMiddleware(dummy_app)
        scope = {"type": "http", "headers": [(b"authorization", b"Bearer tok")]}
        await mw(scope, None, None)

    assert scope["user"] is new_user
    assert 99 in _USER_CACHE


# ── Cache eviction — insertion order (lines 70-71) ───────────────────────────


@pytest.mark.asyncio
@patch("openviper.middleware.auth.decode_access_token")
@patch("openviper.middleware.auth.get_user_by_id")
async def test_cache_eviction_insertion_order(mock_get_user, mock_decode):
    """When cache is full and no entries are expired, oldest entries are evicted."""
    import time

    mock_decode.return_value = {"sub": "77"}
    new_user = MagicMock()
    new_user.is_active = True
    mock_get_user.return_value = new_user

    future = time.monotonic() + 3600.0  # not yet expired

    with patch("openviper.middleware.auth._USER_CACHE_MAXSIZE", 2):
        _USER_CACHE[10] = (MagicMock(), future)
        _USER_CACHE[20] = (MagicMock(), future)

        async def dummy_app(scope, receive, send):
            pass

        mw = AuthenticationMiddleware(dummy_app)
        scope = {"type": "http", "headers": [(b"authorization", b"Bearer tok2")]}
        await mw(scope, None, None)

    assert scope["user"] is new_user
    assert 77 in _USER_CACHE


@pytest.mark.asyncio
@patch("openviper.middleware.auth.decode_access_token")
async def test_auth_jwt_token_expired(mock_decode):
    """TokenExpired exception is caught and falls through to anonymous user."""
    mock_decode.side_effect = TokenExpired()

    async def dummy_app(scope, receive, send):
        pass

    mw = AuthenticationMiddleware(dummy_app)
    scope = {"type": "http", "headers": [(b"authorization", b"Bearer expiredtoken")]}
    await mw(scope, None, None)

    assert isinstance(scope["user"], AnonymousUser)
    assert scope["auth"] == {"type": "none"}


# ── Session exception path (lines 161-162) ───────────────────────────────────


@pytest.mark.asyncio
@patch("openviper.middleware.auth.get_user_from_session")
async def test_auth_session_exception(mock_session):
    """Session lookup exceptions are caught and result in anonymous user."""
    mock_session.side_effect = RuntimeError("DB connection lost")

    async def dummy_app(scope, receive, send):
        pass

    mw = AuthenticationMiddleware(dummy_app)
    scope = {"type": "http", "headers": [(b"cookie", b"session=broken")]}
    await mw(scope, None, None)

    assert isinstance(scope["user"], AnonymousUser)
    assert scope["auth"] == {"type": "none"}


@pytest.mark.asyncio
@patch("openviper.middleware.auth.decode_access_token")
@patch("openviper.middleware.auth.get_user_by_id")
async def test_auth_jwt_cache_hit_expired(mock_get_user, mock_decode):
    import time

    mock_decode.return_value = {"sub": "55"}
    fresh_user = MagicMock()
    fresh_user.is_active = True
    mock_get_user.return_value = fresh_user

    # Pre-populate cache with an ALREADY-EXPIRED entry
    stale_user = MagicMock()
    _USER_CACHE[55] = (stale_user, time.monotonic() - 1.0)

    async def dummy_app(scope, receive, send):
        pass

    mw = AuthenticationMiddleware(dummy_app)
    scope = {"type": "http", "headers": [(b"authorization", b"Bearer sometoken")]}
    await mw(scope, None, None)

    # DB must have been queried since cache entry was expired
    mock_get_user.assert_called_once_with(55)
    # Should return the fresh user from DB, not the stale cached one
    assert scope["user"] is fresh_user
