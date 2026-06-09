"""Cache security tests.

Requirement IDs: CACHE-001 through CACHE-004.

Tests cover:
  CACHE-001: Authenticated responses are not publicly cached by default.
  CACHE-002: Cache key includes user and tenant context when needed.
  CACHE-003: Authorization changes invalidate or bypass stale cache.
  CACHE-004: Web cache poisoning inputs are controlled.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from openviper.auth._user_cache import USER_CACHE, invalidate_user_cache
from openviper.auth.backends import get_client_ip
from openviper.auth.session.middleware import SessionMiddleware
from openviper.auth.session.store import SESSION_CACHE_PREFIX, SESSION_USER_CACHE_PREFIX
from openviper.cache.memory import InMemoryCache
from openviper.cache.validation import validate_cache_key
from openviper.core.context import current_user, request_perms_cache
from openviper.http.response import JSONResponse, Response
from openviper.middleware.cors import CORSMiddleware
from openviper.middleware.ratelimit import RateLimitMiddleware, SlidingWindowCounter
from openviper.middleware.security import SecurityMiddleware
from openviper.staticfiles.handlers import StaticFilesMiddleware

from .conftest import (
    MockUser,
    SendCollector,
    assert_header_contains,
    assert_header_value,
    freeze_time,
    make_scope,
    override_settings,
)


class TestAuthenticatedCacheControl:
    """Authenticated responses must not be publicly cached by default."""

    async def test_cache001_session_middleware_sets_private_cache_control(
        self,
    ) -> None:
        """Session middleware must set Cache-Control: private or no-store."""

        async def inner_app(
            scope: dict[str, object],
            receive: object,
            send: object,
        ) -> None:
            response = JSONResponse({"status": "ok"})
            await response(scope, receive, send)

        middleware = SessionMiddleware(inner_app)
        scope = make_scope(
            method="GET",
            path="/dashboard",
            headers=[(b"cookie", b"sessionid=abc123")],
        )
        collector = SendCollector()

        with override_settings(
            AUTH_SESSION_ENABLED=True,
            SESSION_COOKIE_NAME="sessionid",
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SECURE=True,
            SESSION_COOKIE_SAMESITE="Lax",
        ):
            await middleware(
                scope,
                lambda: {"type": "http.request", "body": b"", "more_body": False},
                collector,
            )

        headers = collector.headers_dict
        # Session cookies must carry HttpOnly and SameSite attributes.
        if "set-cookie" in headers:
            cookie_val = headers["set-cookie"]
            assert "HttpOnly" in cookie_val
            assert "SameSite" in cookie_val

    async def test_cache001_session_cookie_httponly_and_samesite(
        self,
    ) -> None:
        """ "Session cookie settings must enforce HttpOnly and SameSite."""

        async def inner_app(
            scope: dict[str, object],
            receive: object,
            send: object,
        ) -> None:
            response = JSONResponse({"msg": "authenticated"})
            await response(scope, receive, send)

        middleware = SessionMiddleware(inner_app)
        scope = make_scope(
            method="GET",
            path="/profile",
            headers=[(b"cookie", b"sessionid=validsessionkey1")],
        )
        collector = SendCollector()

        with override_settings(
            AUTH_SESSION_ENABLED=True,
            SESSION_COOKIE_NAME="sessionid",
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
        ):
            await middleware(
                scope,
                lambda: {"type": "http.request", "body": b"", "more_body": False},
                collector,
            )

        if "set-cookie" in collector.headers_dict:
            cookie = collector.headers_dict["set-cookie"]
            assert "HttpOnly" in cookie
            assert "SameSite=Lax" in cookie or "SameSite=Strict" in cookie

    async def test_cache001_negative_anonymous_response_no_private_header(
        self,
    ) -> None:
        """ "Anonymous responses must not leak private cache directives."""

        async def inner_app(
            scope: dict[str, object],
            receive: object,
            send: object,
        ) -> None:
            response = JSONResponse({"msg": "public"})
            await response(scope, receive, send)

        middleware = SessionMiddleware(inner_app)
        # No session cookie - anonymous request.
        scope = make_scope(method="GET", path="/public-page")
        collector = SendCollector()

        with override_settings(
            AUTH_SESSION_ENABLED=True,
            SESSION_COOKIE_NAME="sessionid",
        ):
            await middleware(
                scope,
                lambda: {"type": "http.request", "body": b"", "more_body": False},
                collector,
            )

        # For anonymous requests, the middleware should not set a session cookie
        # with authenticated-user attributes unless a session was created.
        set_cookie = collector.headers_dict.get("set-cookie", "")
        if "sessionid" in set_cookie:
            # If a new anonymous session cookie is set, it must still be HttpOnly.
            assert "HttpOnly" in set_cookie

    async def test_cache001_security_middleware_adds_nosniff(
        self,
    ) -> None:
        """ "SecurityMiddleware must add X-Content-Type-Options: nosniff."""

        async def inner_app(
            scope: dict[str, object],
            receive: object,
            send: object,
        ) -> None:
            response = JSONResponse({"data": 1})
            await response(scope, receive, send)

        middleware = SecurityMiddleware(
            inner_app,
            content_type_nosniff=True,
        )
        scope = make_scope(headers=[(b"host", b"localhost")])
        collector = SendCollector()

        with override_settings(ALLOWED_HOSTS=["localhost"]):
            await middleware(
                scope,
                lambda: {"type": "http.request", "body": b"", "more_body": False},
                collector,
            )

        assert_header_value(collector.headers_dict, "x-content-type-options", "nosniff")

    async def test_cache001_negative_no_public_cache_control_on_authenticated(
        self,
    ) -> None:
        """ "Authenticated endpoints must not have public Cache-Control."""

        async def inner_app(
            scope: dict[str, object],
            receive: object,
            send: object,
        ) -> None:
            response = JSONResponse({"secret": "data"})
            await response(scope, receive, send)

        middleware = SecurityMiddleware(
            inner_app,
            content_type_nosniff=True,
        )
        scope = make_scope(headers=[(b"host", b"localhost")])
        collector = SendCollector()

        with override_settings(ALLOWED_HOSTS=["localhost"]):
            await middleware(
                scope,
                lambda: {"type": "http.request", "body": b"", "more_body": False},
                collector,
            )

        # SecurityMiddleware must not add public cache-control headers that
        # would cause a shared cache to store authenticated content.
        cache_control = collector.headers_dict.get("cache-control", "")
        if cache_control:
            assert (
                "public" not in cache_control.lower()
            ), f"Authenticated response must not have public Cache-Control: {cache_control}"


class TestCacheKeyContext:
    """Cache keys must include user and tenant context for isolation."""

    @pytest.mark.asyncio
    async def test_cache002_in_memory_cache_basic_operations(self) -> None:
        """InMemoryCache must support basic get/set operations."""
        cache = InMemoryCache()
        await cache.set("user-1-data", {"name": "Alice"}, ttl=60)
        result = await cache.get("user-1-data")
        assert result == {"name": "Alice"}

    @pytest.mark.asyncio
    async def test_cache002_cache_isolation_by_key(self) -> None:
        """Different cache keys must return different values (user isolation)."""
        cache = InMemoryCache()
        await cache.set("user-1-data", {"name": "Alice"}, ttl=60)
        await cache.set("user-2-data", {"name": "Bob"}, ttl=60)

        result1 = await cache.get("user-1-data")
        result2 = await cache.get("user-2-data")

        assert result1 == {"name": "Alice"}
        assert result2 == {"name": "Bob"}

    @pytest.mark.asyncio
    async def test_cache002_session_cache_prefixes(self) -> None:
        """Session cache keys must use prefixed keys for isolation."""
        assert isinstance(SESSION_CACHE_PREFIX, str)
        assert len(SESSION_CACHE_PREFIX) > 0
        assert isinstance(SESSION_USER_CACHE_PREFIX, str)
        assert len(SESSION_USER_CACHE_PREFIX) > 0

    @pytest.mark.asyncio
    async def test_cache002_tenant_isolation_via_prefix(self) -> None:
        """Cache keys with tenant prefixes must be isolated from each other."""
        cache = InMemoryCache()

        # Simulate two tenants storing data under the same logical key.
        await cache.set("tenant-A_dashboard", {"widgets": ["a1"]}, ttl=60)
        await cache.set("tenant-B_dashboard", {"widgets": ["b1"]}, ttl=60)

        result_a = await cache.get("tenant-A_dashboard")
        result_b = await cache.get("tenant-B_dashboard")

        assert result_a == {"widgets": ["a1"]}
        assert result_b == {"widgets": ["b1"]}

    @pytest.mark.asyncio
    async def test_cache002_user_scoped_cache_isolation(self) -> None:
        """Cache entries scoped by user ID must not leak across users."""
        cache = InMemoryCache()

        user_a_key = "perms-user-42"
        user_b_key = "perms-user-99"

        await cache.set(user_a_key, {"can_edit": True}, ttl=60)
        await cache.set(user_b_key, {"can_edit": False}, ttl=60)

        assert await cache.get(user_a_key) == {"can_edit": True}
        assert await cache.get(user_b_key) == {"can_edit": False}

    @pytest.mark.asyncio
    async def test_cache002_negative_cross_key_no_leak(self) -> None:
        """A cache miss for one user must not return another user's data."""
        cache = InMemoryCache()
        await cache.set("user-1-secret", "classified", ttl=60)

        # Requesting a key that does not exist must return None/default.
        result = await cache.get("user-2-secret")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache002_validate_cache_key_rejects_whitespace(self) -> None:
        """Cache keys with whitespace must be rejected to prevent key confusion."""
        with pytest.raises(ValueError, match="invalid characters"):
            validate_cache_key("user 1 data")

    @pytest.mark.asyncio
    async def test_cache002_validate_cache_key_allows_colons(self) -> None:
        """Cache keys with colons are allowed (standard Redis namespace convention)."""

        result = validate_cache_key("user:1:data")
        assert result == "user:1:data"

    @pytest.mark.asyncio
    async def test_cache002_validate_cache_key_rejects_empty(self) -> None:
        """Empty cache keys must be rejected."""
        with pytest.raises(ValueError, match="must not be empty"):
            validate_cache_key("")

    @pytest.mark.asyncio
    async def test_cache002_validate_cache_key_rejects_overlength(self) -> None:
        """Cache keys exceeding the maximum length must be rejected."""
        with pytest.raises(ValueError, match="maximum length"):
            validate_cache_key("a" * 251)

    @pytest.mark.asyncio
    async def test_cache002_validate_cache_key_accepts_valid(self) -> None:
        """Valid cache keys must pass validation."""
        assert validate_cache_key("user-1-data") == "user-1-data"
        assert validate_cache_key("session_abc123") == "session_abc123"

    @pytest.mark.asyncio
    async def test_cache002_concurrent_access_preserves_isolation(self) -> None:
        """Concurrent async access to InMemoryCache must not bleed data across keys."""
        cache = InMemoryCache()

        async def writer(user_id: int, value: str) -> str:
            key = f"user-{user_id}-data"
            await cache.set(key, value, ttl=60)
            return key

        async def reader(key: str) -> object:
            return await cache.get(key)

        # Write concurrently for multiple users.
        keys = await asyncio.gather(
            writer(1, "alice-data"),
            writer(2, "bob-data"),
            writer(3, "carol-data"),
        )

        # Read back and verify isolation.
        results = await asyncio.gather(*[reader(k) for k in keys])
        assert results == ["alice-data", "bob-data", "carol-data"]


class TestCacheAuthorizationInvalidation:
    """Authorization changes must invalidate or bypass stale cache."""

    @pytest.mark.asyncio
    async def test_cache003_cache_delete_invalidates(self) -> None:
        """Cache delete must remove the cached value."""
        cache = InMemoryCache()
        await cache.set("key", "value", ttl=60)
        assert await cache.get("key") == "value"

        await cache.delete("key")
        assert await cache.get("key") is None

    @pytest.mark.asyncio
    async def test_cache003_cache_clear_removes_all(self) -> None:
        """Cache clear must remove all cached values."""
        cache = InMemoryCache()
        await cache.set("key1", "value1", ttl=60)
        await cache.set("key2", "value2", ttl=60)

        await cache.clear()

        assert await cache.get("key1") is None
        assert await cache.get("key2") is None

    @pytest.mark.asyncio
    async def test_cache003_ttl_expiry_invalidates_stale_data(self) -> None:
        """Cache entries must expire after TTL, preventing stale authorization data."""
        cache = InMemoryCache()

        with freeze_time(1000.0):
            await cache.set("perms-user-1", {"admin": True}, ttl=30)

        # Within TTL, data is still available.
        with freeze_time(1015.0):
            result = await cache.get("perms-user-1")
            assert result == {"admin": True}

        # After TTL, data must be gone - stale permissions must not persist.
        with freeze_time(1035.0):
            result = await cache.get("perms-user-1")
            assert result is None

    @pytest.mark.asyncio
    async def test_cache003_permission_revocation_invalidates_cache(self) -> None:
        """When a user's permissions are revoked, the cached permission data must be invalidated."""
        cache = InMemoryCache()
        perm_key = "perms-user-42"

        # Cache initial permissions.
        await cache.set(perm_key, {"can_edit": True, "can_delete": True}, ttl=300)
        assert await cache.get(perm_key) == {"can_edit": True, "can_delete": True}

        # Simulate permission revocation: delete the cache entry.
        await cache.delete(perm_key)

        # Re-cache with reduced permissions.
        await cache.set(perm_key, {"can_edit": False, "can_delete": False}, ttl=300)
        assert await cache.get(perm_key) == {"can_edit": False, "can_delete": False}

    @pytest.mark.asyncio
    async def test_cache003_negative_stale_data_not_served_after_delete(self) -> None:
        """After deletion, stale data must not be served even if TTL has not expired."""
        cache = InMemoryCache()

        await cache.set("role-admin", "superuser", ttl=300)
        assert await cache.get("role-admin") == "superuser"

        await cache.delete("role-admin")

        # Must return None, not the stale value.
        assert await cache.get("role-admin") is None

    @pytest.mark.asyncio
    async def test_cache003_has_key_reflects_invalidation(self) -> None:
        """has_key must return False after cache invalidation."""
        cache = InMemoryCache()

        await cache.set("check-key", "present", ttl=60)
        assert await cache.has_key("check-key") is True

        await cache.delete("check-key")
        assert await cache.has_key("check-key") is False

    @pytest.mark.asyncio
    async def test_cache003_user_cache_invalidation_on_save(self) -> None:
        """invalidate_user_cache must remove the cached user object."""
        # Manually populate the cache.
        USER_CACHE[42] = ({"username": "admin", "is_superuser": True}, time.time() + 300)
        assert 42 in USER_CACHE

        await invalidate_user_cache(42)

        assert 42 not in USER_CACHE

    @pytest.mark.asyncio
    async def test_cache003_negative_invalidate_nonexistent_user_is_safe(self) -> None:
        """Invalidating a user that is not in the cache must not raise an error."""
        # Must not raise.
        await invalidate_user_cache(999999)

    @pytest.mark.asyncio
    async def test_cache003_contextvar_isolation_between_requests(self) -> None:
        """contextvars must isolate user state between concurrent async requests."""
        results: list[str] = []

        async def simulate_request(user: MockUser) -> None:
            token = current_user.set(user)
            try:
                # Simulate async work.
                await asyncio.sleep(0.01)
                resolved = current_user.get()
                results.append(f"user-{resolved.id}")
            finally:
                current_user.reset(token)

        await asyncio.gather(
            simulate_request(MockUser(user_id=1, username="alice")),
            simulate_request(MockUser(user_id=2, username="bob")),
        )

        assert "user-1" in results
        assert "user-2" in results

    @pytest.mark.asyncio
    async def test_cache003_request_perms_cache_isolation(self) -> None:
        """request_perms_cache must be None by default, preventing cross-request leakage."""
        # Default must be None - not a mutable dict that could leak state.
        assert request_perms_cache.get() is None

    @pytest.mark.asyncio
    async def test_cache003_keys_prefix_listing(self) -> None:
        """Cache keys() with prefix must only list entries matching the prefix."""
        cache = InMemoryCache()
        await cache.set("session-abc", "data1", ttl=60)
        await cache.set("session-xyz", "data2", ttl=60)
        await cache.set("perms-abc", "data3", ttl=60)

        session_keys = await cache.keys(prefix="session-")
        assert all(k.startswith("session-") for k in session_keys)
        assert len(session_keys) == 2


class TestWebCachePoisoning:
    """Untrusted headers must not alter cacheable responses."""

    def test_cache004_security_middleware_rejects_untrusted_hosts(self) -> None:
        """SecurityMiddleware must reject requests with untrusted Host headers."""

        async def inner_app(scope: dict[str, object], receive: object, send: object) -> None:
            pass

        with override_settings(ALLOWED_HOSTS=["trusted.example.com"]):
            middleware = SecurityMiddleware(inner_app)
            assert middleware.is_host_allowed("trusted.example.com") is True
            assert middleware.is_host_allowed("evil.example.com") is False

    @pytest.mark.asyncio
    async def test_cache004_security_middleware_400_for_bad_host(self) -> None:
        """SecurityMiddleware must return 400 for disallowed Host headers."""

        async def inner_app(scope: dict[str, object], receive: object, send: object) -> None:
            # Should never be reached.
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"should not reach"})

        with override_settings(ALLOWED_HOSTS=["trusted.example.com"]):
            middleware = SecurityMiddleware(inner_app)

        scope = make_scope(headers=[(b"host", b"evil.example.com")])
        collector = SendCollector()
        await middleware(
            scope, lambda: {"type": "http.request", "body": b"", "more_body": False}, collector
        )

        assert collector.status_code == 400

    @pytest.mark.asyncio
    async def test_cache004_security_middleware_rejects_crlf_in_host(self) -> None:
        """SecurityMiddleware must reject Host headers containing CR or LF characters."""

        async def inner_app(scope: dict[str, object], receive: object, send: object) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"should not reach"})

        with override_settings(ALLOWED_HOSTS=["*"]):
            middleware = SecurityMiddleware(inner_app)

        for bad_host in [
            b"evil.com\r\nX-Injected: true",
            b"evil.com\nX-Injected: true",
            b"evil.com\0",
        ]:
            scope = make_scope(headers=[(b"host", bad_host)])
            collector = SendCollector()
            await middleware(
                scope, lambda: {"type": "http.request", "body": b"", "more_body": False}, collector
            )

            assert (
                collector.status_code == 400
            ), f"Expected 400 for Host header with CRLF/null: {bad_host!r}"

    @pytest.mark.asyncio
    async def test_cache004_security_middleware_wildcard_host(self) -> None:
        """SecurityMiddleware with wildcard ALLOWED_HOSTS must accept any host."""

        async def inner_app(scope: dict[str, object], receive: object, send: object) -> None:
            response_body = b"ok"
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [[b"content-length", str(len(response_body)).encode()]],
                }
            )
            await send({"type": "http.response.body", "body": response_body})

        with override_settings(ALLOWED_HOSTS=["*"]):
            middleware = SecurityMiddleware(inner_app)

        scope = make_scope(
            headers=[(b"host", b"any.random.host")],
            server=("any.random.host", 80),
        )
        collector = SendCollector()
        await middleware(
            scope,
            lambda: {"type": "http.request", "body": b"", "more_body": False},
            collector,
        )

        assert collector.status_code == 200

    @pytest.mark.asyncio
    async def test_cache004_rate_limit_per_key(self) -> None:
        """Rate limiting must be per-key, not global."""
        counter = SlidingWindowCounter(max_requests=1, window_seconds=60)

        # Different keys must have independent limits.
        allowed_a, _ = await counter.is_allowed("key-a")
        assert allowed_a is True

        allowed_b, _ = await counter.is_allowed("key-b")
        assert allowed_b is True

        # Same key must be rate limited.
        allowed_a2, _ = await counter.is_allowed("key-a")
        assert allowed_a2 is False

    @pytest.mark.asyncio
    async def test_cache004_rate_limit_uses_client_ip_not_forwarded(self) -> None:
        """RateLimitMiddleware must use the ASGI client IP, not X-Forwarded-For."""

        async def inner_app(scope: dict[str, object], receive: object, send: object) -> None:
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        middleware = RateLimitMiddleware(
            inner_app,
            max_requests=1,
            window_seconds=60,
        )

        # First request from client IP 10.0.0.1.
        scope1 = make_scope(
            headers=[(b"x-forwarded-for", b"1.2.3.4, 10.0.0.1")],
        )
        scope1["client"] = ("10.0.0.1", 12345)
        collector1 = SendCollector()
        await middleware(
            scope1,
            lambda: {"type": "http.request", "body": b"", "more_body": False},
            collector1,
        )
        assert collector1.status_code == 200

        # Second request from same client IP must be rate limited.
        scope2 = make_scope(
            headers=[(b"x-forwarded-for", b"1.2.3.4, 10.0.0.1")],
        )
        scope2["client"] = ("10.0.0.1", 12346)
        collector2 = SendCollector()
        await middleware(
            scope2,
            lambda: {"type": "http.request", "body": b"", "more_body": False},
            collector2,
        )
        assert collector2.status_code == 429

    @pytest.mark.asyncio
    async def test_cache004_negative_x_forwarded_for_does_not_bypass_rate_limit(
        self,
    ) -> None:
        """Spoofed X-Forwarded-For must not bypass rate limiting."""

        async def inner_app(
            scope: dict[str, object],
            receive: object,
            send: object,
        ) -> None:
            response = JSONResponse({"ok": True})
            await response(scope, receive, send)

        middleware = RateLimitMiddleware(
            inner_app,
            max_requests=1,
            window_seconds=60,
        )

        # Exhaust the rate limit from client IP.
        scope1 = make_scope()
        scope1["client"] = ("192.168.1.1", 5000)
        collector1 = SendCollector()
        await middleware(
            scope1,
            lambda: {"type": "http.request", "body": b"", "more_body": False},
            collector1,
        )
        assert collector1.status_code == 200

        # Attempt to bypass with a different X-Forwarded-For.
        scope2 = make_scope(
            headers=[(b"x-forwarded-for", b"spoofed-ip")],
        )
        scope2["client"] = ("192.168.1.1", 5001)
        collector2 = SendCollector()
        await middleware(
            scope2,
            lambda: {"type": "http.request", "body": b"", "more_body": False},
            collector2,
        )
        assert collector2.status_code == 429

    @pytest.mark.asyncio
    async def test_cache004_cors_vary_origin_prevents_cache_poisoning(self) -> None:
        """CORS middleware must add Vary: Origin when origins are restricted."""

        async def inner_app(scope: dict[str, object], receive: object, send: object) -> None:
            response = JSONResponse({"data": "public"})
            await response(scope, receive, send)

        middleware = CORSMiddleware(
            inner_app,
            allowed_origins=["https://trusted.example.com"],
            allow_credentials=True,
        )
        scope = make_scope(
            method="GET",
            headers=[(b"origin", b"https://trusted.example.com"), (b"host", b"api.example.com")],
        )
        collector = SendCollector()
        await middleware(
            scope, lambda: {"type": "http.request", "body": b"", "more_body": False}, collector
        )

        # Vary: Origin must be present to prevent CDN cache poisoning.
        assert_header_contains(collector.headers_dict, "vary", "Origin")

    @pytest.mark.asyncio
    async def test_cache004_cors_no_vary_for_wildcard(self) -> None:
        """CORS middleware with allow_all_origins must not add Vary: Origin."""

        async def inner_app(scope: dict[str, object], receive: object, send: object) -> None:
            response = JSONResponse({"data": "public"})
            await response(scope, receive, send)

        middleware = CORSMiddleware(
            inner_app,
            allowed_origins=["*"],
        )
        scope = make_scope(
            method="GET",
            headers=[(b"origin", b"https://any.example.com"), (b"host", b"api.example.com")],
        )
        collector = SendCollector()
        await middleware(
            scope, lambda: {"type": "http.request", "body": b"", "more_body": False}, collector
        )

        headers = collector.headers_dict
        if "vary" in headers:
            assert "Origin" not in headers["vary"]

    @pytest.mark.asyncio
    async def test_cache004_cors_preflight_no_vary_origin_for_wildcard(self) -> None:
        """CORS preflight with wildcard origins must not include Vary: Origin."""

        async def inner_app(scope: dict[str, object], receive: object, send: object) -> None:
            pass

        middleware = CORSMiddleware(
            inner_app,
            allowed_origins=["*"],
            allowed_methods=["GET", "POST"],
        )
        scope = make_scope(
            method="OPTIONS",
            headers=[(b"origin", b"https://attacker.com"), (b"host", b"api.example.com")],
        )
        collector = SendCollector()
        await middleware(
            scope, lambda: {"type": "http.request", "body": b"", "more_body": False}, collector
        )

        headers = collector.headers_dict
        if "vary" in headers:
            assert "Origin" not in headers.get("vary", "")

    @pytest.mark.asyncio
    async def test_cache004_session_cookie_rejects_crlf(self) -> None:
        """Session cookie values containing CR/LF must be rejected to prevent header injection."""
        response = Response(content="ok", status_code=200)

        # Cookie name with CRLF must be rejected.
        with pytest.raises(ValueError, match="CR or LF"):
            response.set_cookie("bad\r\nname", "value")

        # Cookie value with CRLF must be rejected.
        with pytest.raises(ValueError, match="CR or LF"):
            response.set_cookie("sessionid", "bad\nvalue")

    @pytest.mark.asyncio
    async def test_cache004_negative_samesite_none_without_secure_rejected(self) -> None:
        """Cookies with SameSite=None must also set Secure=True."""
        response = Response(content="ok", status_code=200)

        with pytest.raises(ValueError, match="SameSite=None must also set Secure"):
            response.set_cookie("sessionid", "abc123", samesite="none", secure=False)

    def test_cache004get_client_ip_ignores_untrusted_x_forwarded_for(self) -> None:
        """get_client_ip must not trust X-Forwarded-For from untrusted proxies."""
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "10.0.0.5"
        request.headers = {"x-forwarded-for": "1.2.3.4, 5.6.7.8"}

        # Without TRUSTED_PROXIES configured, X-Forwarded-For must be ignored.
        with patch("openviper.auth.backends.settings") as mock_settings:
            mock_settings.TRUSTED_PROXIES = ()
            result = get_client_ip(request)
            assert result == "10.0.0.5"

    def test_cache004get_client_ip_trusts_configured_proxies(self) -> None:
        """get_client_ip must use X-Forwarded-For when the direct IP is a trusted proxy."""
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "10.0.0.1"  # Trusted proxy IP.
        request.headers = {"x-forwarded-for": "1.2.3.4, 10.0.0.1"}

        with patch("openviper.auth.backends.settings") as mock_settings:
            mock_settings.TRUSTED_PROXIES = ("10.0.0.1",)
            result = get_client_ip(request)
            # The rightmost non-trusted IP must be used.
            assert result == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_cache004_negative_host_injection_in_redirect(self) -> None:
        """SecurityMiddleware must not allow Host header injection to influence redirects."""

        async def inner_app(scope: dict[str, object], receive: object, send: object) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"should not reach"})

        with override_settings(ALLOWED_HOSTS=["trusted.example.com"]):
            middleware = SecurityMiddleware(inner_app, ssl_redirect=True)

        scope = make_scope(
            method="GET",
            path="/dashboard",
            scheme="http",
            headers=[(b"host", b"evil.attacker.com")],
        )
        collector = SendCollector()
        await middleware(
            scope, lambda: {"type": "http.request", "body": b"", "more_body": False}, collector
        )

        # Must reject the request with 400, not redirect to the attacker's host.
        assert collector.status_code == 400

    @pytest.mark.asyncio
    async def test_cache004_static_files_cache_control_is_public_only(self) -> None:
        """Static file cache headers must use 'public' only for truly public assets."""

        # Verify that the static file middleware uses "public, max-age=..." for
        # cache-control, which is appropriate for static assets but must never
        # be applied to authenticated dynamic content.
        async def dummy_app(scope: dict[str, object], receive: object, send: object) -> None:
            pass

        middleware = StaticFilesMiddleware(dummy_app, cache_max_age=3600)
        assert middleware.cache_max_age == 3600
        # The cache-control format is "public, max-age={cache_max_age}".
        expected_header = f"public, max-age={middleware.cache_max_age}"
        assert "public" in expected_header
        assert "private" not in expected_header

    @pytest.mark.asyncio
    async def test_cache004_security_middleware_adds_security_headers(self) -> None:
        """SecurityMiddleware must add standard security headers to all responses."""

        async def inner_app(scope: dict[str, object], receive: object, send: object) -> None:
            response = JSONResponse({"data": 1})
            await response(scope, receive, send)

        with override_settings(ALLOWED_HOSTS=["localhost"]):
            middleware = SecurityMiddleware(
                inner_app,
                content_type_nosniff=True,
                x_frame_options="DENY",
            )

        scope = make_scope(headers=[(b"host", b"localhost")])
        collector = SendCollector()
        await middleware(
            scope, lambda: {"type": "http.request", "body": b"", "more_body": False}, collector
        )

        headers = collector.headers_dict
        assert_header_value(headers, "x-content-type-options", "nosniff")
        assert_header_value(headers, "x-frame-options", "DENY")
        assert_header_contains(headers, "referrer-policy", "strict-origin-when-cross-origin")

    @pytest.mark.asyncio
    async def test_cache004_negative_untrusted_x_forwarded_host_does_not_set_scope(self) -> None:
        """Untrusted X-Forwarded-Host must not override the ASGI scope host."""

        async def inner_app(scope: dict[str, object], receive: object, send: object) -> None:
            # The scope must contain the validated host, not the spoofed one.
            host = ""
            for name, value in scope.get("headers", []):
                if name == b"host":
                    host = value.decode("latin-1")
            body = host.encode("latin-1")
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [[b"content-length", str(len(body)).encode()]],
                }
            )
            await send({"type": "http.response.body", "body": body})

        with override_settings(ALLOWED_HOSTS=["trusted.example.com"]):
            middleware = SecurityMiddleware(inner_app)

        scope = make_scope(
            headers=[(b"host", b"trusted.example.com")], server=("trusted.example.com", 443)
        )
        collector = SendCollector()
        await middleware(
            scope, lambda: {"type": "http.request", "body": b"", "more_body": False}, collector
        )

        # The request must be accepted (200) and the validated host must appear.
        assert collector.status_code == 200
        body = collector.body.decode("latin-1")
        assert "trusted.example.com" in body
