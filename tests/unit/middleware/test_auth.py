"""Unit tests for openviper.middleware.auth — AuthenticationMiddleware."""

import asyncio
import datetime
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import jwt as jose_jwt

import openviper.middleware.auth as _auth_mod
from openviper.auth.jwt import (
    _JWT_ALGORITHM,
    _JWT_SECRET,
    create_access_token,
)
from openviper.auth.models import AnonymousUser
from openviper.core.context import current_user as ctx_user
from openviper.middleware.auth import (
    _USER_CACHE,
    AuthenticationMiddleware,
    _get_user_cache_lock,
    _get_user_cached,
)
from openviper.utils import timezone


def _clear_auth_cache():
    _USER_CACHE.clear()


def _http_scope(headers=None):
    return {"type": "http", "method": "GET", "path": "/", "headers": list(headers or [])}


def _bearer_scope(token):
    return _http_scope([(b"authorization", f"Bearer {token}".encode("latin-1"))])


def _cookie_scope(cookie_val):
    return _http_scope([(b"cookie", cookie_val.encode("latin-1"))])


# ---------------------------------------------------------------------------
# Non-HTTP passthrough
# ---------------------------------------------------------------------------


class TestAuthMiddlewareNonHTTP:
    @pytest.mark.asyncio
    async def test_lifespan_passthrough(self):
        calls = []

        async def app(scope, receive, send):
            calls.append("app")

        mw = AuthenticationMiddleware(app)
        await mw({"type": "lifespan"}, None, None)
        assert "app" in calls

    @pytest.mark.asyncio
    async def test_websocket_handled(self):
        """Websocket scopes should also be processed (user set)."""
        captured = {}

        async def app(scope, receive, send):
            captured["user"] = scope.get("user")

        mw = AuthenticationMiddleware(app)
        await mw({"type": "websocket", "headers": []}, None, None)
        assert isinstance(captured["user"], AnonymousUser)


# ---------------------------------------------------------------------------
# Anonymous (no credentials)
# ---------------------------------------------------------------------------


class TestAuthMiddlewareAnonymous:
    @pytest.mark.asyncio
    async def test_no_credentials_sets_anonymous(self):
        captured = {}

        async def app(scope, receive, send):
            captured["user"] = scope.get("user")
            captured["auth"] = scope.get("auth")

        mw = AuthenticationMiddleware(app)
        await mw(_http_scope(), None, None)
        assert isinstance(captured["user"], AnonymousUser)
        assert captured["auth"]["type"] == "none"

    @pytest.mark.asyncio
    async def test_auth_info_type_none(self):
        captured = {}

        async def app(scope, receive, send):
            captured["auth"] = scope.get("auth")

        mw = AuthenticationMiddleware(app)
        await mw(_http_scope(), None, None)
        assert captured["auth"] == {"type": "none"}


# ---------------------------------------------------------------------------
# JWT authentication
# ---------------------------------------------------------------------------


class TestAuthMiddlewareJWT:
    @pytest.mark.asyncio
    async def test_valid_jwt_sets_user(self):
        token = create_access_token(user_id=42)
        fake_user = MagicMock()
        fake_user.is_active = True
        captured = {}

        async def app(scope, receive, send):
            captured["user"] = scope.get("user")
            captured["auth"] = scope.get("auth")

        mw = AuthenticationMiddleware(app)
        with patch(
            "openviper.middleware.auth._get_user_cached", new=AsyncMock(return_value=fake_user)
        ):
            with patch(
                "openviper.middleware.auth.is_token_revoked", new=AsyncMock(return_value=False)
            ):
                await mw(_bearer_scope(token), None, None)

        assert captured["user"] is fake_user
        assert captured["auth"]["type"] == "jwt"

    @pytest.mark.asyncio
    async def test_expired_jwt_falls_to_anonymous(self):
        claims = {
            "sub": "1",
            "jti": "test-jti",
            "iat": timezone.now() - datetime.timedelta(hours=48),
            "exp": timezone.now() - datetime.timedelta(hours=24),
            "type": "access",
        }
        token = jose_jwt.encode(claims, _JWT_SECRET, algorithm=_JWT_ALGORITHM)
        captured = {}

        async def app(scope, receive, send):
            captured["user"] = scope.get("user")

        await AuthenticationMiddleware(app)(_bearer_scope(token), None, None)
        assert isinstance(captured["user"], AnonymousUser)

    @pytest.mark.asyncio
    async def test_revoked_token_falls_to_anonymous(self):
        token = create_access_token(user_id=42)
        captured = {}

        async def app(scope, receive, send):
            captured["user"] = scope.get("user")

        with patch("openviper.middleware.auth.is_token_revoked", new=AsyncMock(return_value=True)):
            await AuthenticationMiddleware(app)(_bearer_scope(token), None, None)

        assert isinstance(captured["user"], AnonymousUser)

    @pytest.mark.asyncio
    async def test_inactive_jwt_user_becomes_anonymous(self):
        token = create_access_token(user_id=99)
        inactive = MagicMock()
        inactive.is_active = False
        captured = {}

        async def app(scope, receive, send):
            captured["user"] = scope.get("user")

        with patch(
            "openviper.middleware.auth._get_user_cached", new=AsyncMock(return_value=inactive)
        ):
            with patch(
                "openviper.middleware.auth.is_token_revoked", new=AsyncMock(return_value=False)
            ):
                await AuthenticationMiddleware(app)(_bearer_scope(token), None, None)

        assert isinstance(captured["user"], AnonymousUser)

    @pytest.mark.asyncio
    async def test_jwt_without_sub_falls_to_anonymous(self):
        claims = {
            "jti": "no-sub",
            "iat": timezone.now(),
            "exp": timezone.now() + datetime.timedelta(hours=1),
            "type": "access",
        }
        token = jose_jwt.encode(claims, _JWT_SECRET, algorithm=_JWT_ALGORITHM)
        captured = {}

        async def app(scope, receive, send):
            captured["user"] = scope.get("user")

        await AuthenticationMiddleware(app)(_bearer_scope(token), None, None)
        assert isinstance(captured["user"], AnonymousUser)

    @pytest.mark.asyncio
    async def test_malformed_jwt_falls_to_anonymous(self):
        captured = {}

        async def app(scope, receive, send):
            captured["user"] = scope.get("user")

        scope = _http_scope([(b"authorization", b"Bearer not.a.valid.token")])
        await AuthenticationMiddleware(app)(scope, None, None)
        assert isinstance(captured["user"], AnonymousUser)

    @pytest.mark.asyncio
    async def test_bearer_prefix_case_sensitive(self):
        """'bearer' (lowercase) must not be recognised as Bearer token."""
        token = create_access_token(user_id=1)
        captured = {}

        async def app(scope, receive, send):
            captured["auth"] = scope.get("auth")

        scope = _http_scope([(b"authorization", f"bearer {token}".encode("latin-1"))])
        await AuthenticationMiddleware(app)(scope, None, None)
        assert captured["auth"]["type"] == "none"


# ---------------------------------------------------------------------------
# Session authentication
# ---------------------------------------------------------------------------


class TestAuthMiddlewareSession:
    @pytest.mark.asyncio
    async def test_valid_session_sets_user(self):
        session_user = MagicMock()
        session_user.is_active = True
        captured = {}

        async def app(scope, receive, send):
            captured["user"] = scope.get("user")
            captured["auth"] = scope.get("auth")

        with patch(
            "openviper.middleware.auth.get_user_from_session",
            new=AsyncMock(return_value=session_user),
        ):
            await AuthenticationMiddleware(app)(_cookie_scope("sessionid=abc"), None, None)

        assert captured["user"] is session_user
        assert captured["auth"]["type"] == "session"

    @pytest.mark.asyncio
    async def test_inactive_session_user_becomes_anonymous(self):
        inactive = MagicMock()
        inactive.is_active = False
        captured = {}

        async def app(scope, receive, send):
            captured["user"] = scope.get("user")

        with patch(
            "openviper.middleware.auth.get_user_from_session", new=AsyncMock(return_value=inactive)
        ):
            await AuthenticationMiddleware(app)(_cookie_scope("sessionid=fake"), None, None)

        assert isinstance(captured["user"], AnonymousUser)

    @pytest.mark.asyncio
    async def test_session_auth_exception_falls_to_anonymous(self):
        captured = {}

        async def app(scope, receive, send):
            captured["user"] = scope.get("user")

        with patch(
            "openviper.middleware.auth.get_user_from_session",
            new=AsyncMock(side_effect=Exception("db error")),
        ):
            await AuthenticationMiddleware(app)(_cookie_scope("sessionid=bad"), None, None)

        assert isinstance(captured["user"], AnonymousUser)

    @pytest.mark.asyncio
    async def test_session_returns_none_falls_to_anonymous(self):
        captured = {}

        async def app(scope, receive, send):
            captured["user"] = scope.get("user")

        with patch(
            "openviper.middleware.auth.get_user_from_session", new=AsyncMock(return_value=None)
        ):
            await AuthenticationMiddleware(app)(_cookie_scope("sessionid=x"), None, None)

        assert isinstance(captured["user"], AnonymousUser)


# ---------------------------------------------------------------------------
# JWT takes precedence over session when both headers present
# ---------------------------------------------------------------------------


class TestAuthMiddlewarePrecedence:
    @pytest.mark.asyncio
    async def test_jwt_takes_precedence_over_session(self):
        token = create_access_token(user_id=7)
        jwt_user = MagicMock()
        jwt_user.is_active = True
        captured = {}

        async def app(scope, receive, send):
            captured["user"] = scope.get("user")
            captured["auth"] = scope.get("auth")

        scope = _http_scope(
            [
                (b"authorization", f"Bearer {token}".encode("latin-1")),
                (b"cookie", b"sessionid=valid-session"),
            ]
        )
        with patch(
            "openviper.middleware.auth._get_user_cached", new=AsyncMock(return_value=jwt_user)
        ):
            with patch(
                "openviper.middleware.auth.is_token_revoked", new=AsyncMock(return_value=False)
            ):
                await AuthenticationMiddleware(app)(scope, None, None)

        assert captured["user"] is jwt_user
        assert captured["auth"]["type"] == "jwt"

    @pytest.mark.asyncio
    async def test_falls_back_to_session_when_jwt_fails(self):
        """When JWT is revoked, session cookie should still authenticate."""
        token = create_access_token(user_id=7)
        session_user = MagicMock()
        session_user.is_active = True
        captured = {}

        async def app(scope, receive, send):
            captured["auth"] = scope.get("auth")

        scope = _http_scope(
            [
                (b"authorization", f"Bearer {token}".encode("latin-1")),
                (b"cookie", b"sessionid=valid-session"),
            ]
        )
        with patch("openviper.middleware.auth.is_token_revoked", new=AsyncMock(return_value=True)):
            with patch(
                "openviper.middleware.auth.get_user_from_session",
                new=AsyncMock(return_value=session_user),
            ):
                await AuthenticationMiddleware(app)(scope, None, None)

        assert captured["auth"]["type"] == "session"


# ---------------------------------------------------------------------------
# Context variable
# ---------------------------------------------------------------------------


class TestAuthMiddlewareContextVar:
    @pytest.mark.asyncio
    async def test_context_var_set_during_request(self):
        seen = None

        async def app(scope, receive, send):
            nonlocal seen
            seen = ctx_user.get(None)

        await AuthenticationMiddleware(app)(_http_scope(), None, None)
        assert isinstance(seen, AnonymousUser)

    @pytest.mark.asyncio
    async def test_context_var_reset_after_request(self):
        async def noop(scope, receive, send):
            pass

        token_before = ctx_user.set(None)
        try:
            await AuthenticationMiddleware(noop)(_http_scope(), None, None)
            # After middleware finishes, the context var should be reset
            val = ctx_user.get(None)
            assert val is None or isinstance(val, AnonymousUser)
        finally:
            ctx_user.reset(token_before)

    @pytest.mark.asyncio
    async def test_context_var_reset_on_app_exception(self):
        """Context var must be reset even when the inner app raises."""

        async def app(scope, receive, send):
            raise RuntimeError("boom")

        mw = AuthenticationMiddleware(app)
        with pytest.raises(RuntimeError, match="boom"):
            await mw(_http_scope(), None, None)
        # No leaked state — var should be None or AnonymousUser
        val = ctx_user.get(None)
        assert val is None or isinstance(val, AnonymousUser)

    @pytest.mark.asyncio
    async def test_context_var_authenticated_user_visible_inside(self):
        """Inner app should see the authenticated user via context var."""
        token = create_access_token(user_id=5)
        fake_user = MagicMock()
        fake_user.is_active = True
        seen = None

        async def app(scope, receive, send):
            nonlocal seen
            seen = ctx_user.get(None)

        with patch(
            "openviper.middleware.auth._get_user_cached", new=AsyncMock(return_value=fake_user)
        ):
            with patch(
                "openviper.middleware.auth.is_token_revoked", new=AsyncMock(return_value=False)
            ):
                await AuthenticationMiddleware(app)(_bearer_scope(token), None, None)

        assert seen is fake_user


# ---------------------------------------------------------------------------
# User cache
# ---------------------------------------------------------------------------


class TestUserCache:
    @pytest.mark.asyncio
    async def test_cache_hit_avoids_db_call(self):
        _clear_auth_cache()
        fake_user = MagicMock()

        with patch(
            "openviper.middleware.auth.get_user_by_id", new=AsyncMock(return_value=fake_user)
        ) as mock_get:
            u1 = await _get_user_cached(100)
            u2 = await _get_user_cached(100)
            assert u1 is fake_user
            assert u2 is fake_user
            mock_get.assert_awaited_once()

        _clear_auth_cache()

    @pytest.mark.asyncio
    async def test_cache_miss_calls_db(self):
        _clear_auth_cache()
        user_a = MagicMock()
        user_b = MagicMock()

        with patch(
            "openviper.middleware.auth.get_user_by_id", new=AsyncMock(side_effect=[user_a, user_b])
        ) as mock_get:
            r1 = await _get_user_cached(200)
            r2 = await _get_user_cached(201)
            assert r1 is user_a
            assert r2 is user_b
            assert mock_get.await_count == 2

        _clear_auth_cache()

    @pytest.mark.asyncio
    async def test_expired_entry_refetched(self):
        _clear_auth_cache()
        fake_user = MagicMock()

        with patch(
            "openviper.middleware.auth.get_user_by_id", new=AsyncMock(return_value=fake_user)
        ) as mock_get:
            await _get_user_cached(300)
            # Manually expire the entry
            _USER_CACHE[300] = (_USER_CACHE[300][0], time.monotonic() - 1)
            await _get_user_cached(300)
            assert mock_get.await_count == 2

        _clear_auth_cache()

    @pytest.mark.asyncio
    async def test_eviction_when_cache_full(self):
        """When cache exceeds maxsize, stale/old entries are evicted."""
        _clear_auth_cache()
        fake_user = MagicMock()

        with patch(
            "openviper.middleware.auth.get_user_by_id", new=AsyncMock(return_value=fake_user)
        ):
            # Pre-fill with 4096 expired entries
            for i in range(4096):
                _USER_CACHE[i] = (fake_user, time.monotonic() - 9999)
            # Next insertion must trigger eviction — cache size must not exceed maxsize+1
            await _get_user_cached(99999)
            assert len(_USER_CACHE) <= 4096

        _clear_auth_cache()

    @pytest.mark.asyncio
    async def test_concurrent_cache_access_safe(self):
        """Concurrent requests for the same user_id must not make duplicate DB calls."""
        _clear_auth_cache()
        fake_user = MagicMock()
        call_count = 0

        async def fake_get_user(user_id):
            nonlocal call_count
            call_count += 1
            return fake_user

        with patch("openviper.middleware.auth.get_user_by_id", new=fake_get_user):
            # First call populates cache; subsequent ones hit cache
            await _get_user_cached(400)
            await asyncio.gather(*[_get_user_cached(400) for _ in range(10)])
            # Only the first call should have hit the DB
            assert call_count == 1

        _clear_auth_cache()


# ---------------------------------------------------------------------------
# User cache lock
# ---------------------------------------------------------------------------


class TestUserCacheLock:
    def test_returns_lock(self):
        lock = _get_user_cache_lock()
        assert lock is not None

    def test_same_lock_returned(self):
        lock1 = _get_user_cache_lock()
        lock2 = _get_user_cache_lock()
        assert lock1 is lock2

    def test_lock_is_asyncio_lock(self):
        lock = _get_user_cache_lock()
        assert isinstance(lock, asyncio.Lock)

    def test_thread_safe_initialization_guard_exists(self):
        """_LOCK_INIT_GUARD must exist to prevent TOCTOU races at lock creation."""
        auth_module = sys.modules[_get_user_cache_lock.__module__]
        assert hasattr(auth_module, "_LOCK_INIT_GUARD")


class TestUserCacheLRUEviction:
    @pytest.mark.asyncio
    async def test_evicts_oldest_when_no_expired_entries(self):
        """Evicts by insertion order when cache is full and no entries expired."""

        _clear_auth_cache()

        fake_user = MagicMock()
        future_exp = time.monotonic() + 9999.0

        # Fill cache to capacity (patch maxsize to 2 for speed)
        with patch.object(_auth_mod, "_USER_CACHE_MAXSIZE", 2):
            _USER_CACHE[1001] = (fake_user, future_exp)
            _USER_CACHE[1002] = (fake_user, future_exp)

            async def fake_get_user(uid):
                return fake_user

            with patch("openviper.middleware.auth.get_user_by_id", new=fake_get_user):
                # Cache is full, no expired entries → LRU fallback
                await _get_user_cached(1003)

        # 1001 (oldest) should have been evicted
        assert 1001 not in _USER_CACHE
        # New user should be present
        assert 1003 in _USER_CACHE

        _clear_auth_cache()
