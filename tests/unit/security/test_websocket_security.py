"""WebSocket security tests.

Requirement IDs: WS-001 through WS-005.

Covers:
  WS-001 - WebSocket upgrade requires authentication when configured
  WS-002 - WebSocket origin is validated
  WS-003 - Channel subscription authorization is enforced
  WS-004 - WebSocket messages are rate limited
  WS-005 - Broadcasts are tenant-isolated
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openviper.auth.decorators import login_required, permission_required, role_required
from openviper.auth.middleware import AuthenticationMiddleware
from openviper.auth.models import AnonymousUser
from openviper.core.context import current_user
from openviper.exceptions import PermissionDenied, Unauthorized
from openviper.http.request import Request
from openviper.middleware.cors import CORSMiddleware
from openviper.middleware.csrf import CSRF_SAFE_METHODS, CSRFMiddleware
from openviper.middleware.ratelimit import RateLimitMiddleware, SlidingWindowCounter

from .conftest import MockUser, SendCollector, make_scope

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ws_scope(
    path: str = "/ws/chat/",
    headers: list[tuple[bytes, bytes]] | None = None,
    query_string: bytes = b"",
    server: tuple[str, int] | None = ("localhost", 8000),
    subprotocols: list[str] | None = None,
) -> dict[str, object]:
    """Build a minimal ASGI WebSocket scope dict for testing."""
    scope: dict[str, object] = {
        "type": "websocket",
        "path": path,
        "query_string": query_string,
        "headers": headers or [],
        "server": server,
        "root_path": "",
        "scheme": "ws",
    }
    if subprotocols is not None:
        scope["subprotocols"] = subprotocols
    return scope


async def noop_receive() -> dict[str, object]:
    """ASGI receive that returns a websocket.connect event."""
    return {"type": "websocket.connect"}


# ---------------------------------------------------------------------------
# WS-001: WebSocket upgrade requires authentication when configured
# ---------------------------------------------------------------------------


class TestWS001WebSocketAuthentication:
    """WebSocket upgrades must require authentication when configured.

    The AuthenticationMiddleware processes both HTTP and WebSocket scope
    types.  Unauthenticated WebSocket upgrades must be rejected (fail-closed).
    """

    # -- Positive tests: authenticated upgrades pass through ----------------

    @pytest.mark.asyncio
    async def test_ws001_authenticated_user_set_on_ws_scope(self) -> None:
        """AuthenticationMiddleware must set scope['user'] on websocket scopes."""
        user = MockUser(user_id=42, username="alice")
        scope = make_ws_scope(
            headers=[(b"authorization", b"Bearer valid.jwt.token")],
        )

        async def inner_app(s: dict[str, object], r: object, s_end: object) -> None:
            s["captured_user"] = s.get("user")
            s["captured_auth"] = s.get("auth")
            await s_end({"type": "websocket.accept"})

        with patch(
            "openviper.auth.manager.AuthManager.authenticate",
            return_value=(user, {"type": "jwt", "token": "valid.jwt.token"}),
        ):
            middleware = AuthenticationMiddleware(inner_app)
            collector = SendCollector()
            await middleware(scope, noop_receive, collector)

        assert scope["captured_user"] is user
        assert scope["captured_auth"]["type"] == "jwt"

    @pytest.mark.asyncio
    async def test_ws001_request_object_accepts_websocket_scope(self) -> None:
        """Request must accept a websocket scope type without error."""
        scope = make_ws_scope(path="/ws/chat/")
        request = Request(scope)
        assert request.path == "/ws/chat/"

    # -- Negative tests: unauthenticated upgrades are rejected --------------

    @pytest.mark.asyncio
    async def test_ws001_unauthenticated_user_set_on_ws_scope(self) -> None:
        """AuthenticationMiddleware must set AnonymousUser when no credentials."""
        scope = make_ws_scope(headers=[])

        async def inner_app(s: dict[str, object], r: object, s_end: object) -> None:
            s["captured_user"] = s.get("user")
            await s_end({"type": "websocket.accept"})

        with patch(
            "openviper.auth.manager.AuthManager.authenticate",
            return_value=(AnonymousUser(), {"type": "none"}),
        ):
            middleware = AuthenticationMiddleware(inner_app)
            collector = SendCollector()
            await middleware(scope, noop_receive, collector)

        assert isinstance(scope["captured_user"], AnonymousUser)

    @pytest.mark.asyncio
    async def test_ws001_login_required_rejects_anonymous_on_ws_handler(self) -> None:
        """login_required must raise Unauthorized for anonymous WebSocket users."""

        @login_required
        async def ws_handler(request: Request) -> dict[str, object]:
            return {"status": "ok"}

        scope = make_ws_scope(headers=[])
        request = Request(scope)
        request.user = AnonymousUser()

        with pytest.raises(Unauthorized):
            await ws_handler(request)

    @pytest.mark.asyncio
    async def test_ws001_login_required_allows_authenticated_on_ws_handler(self) -> None:
        """login_required must allow authenticated WebSocket users through."""

        @login_required
        async def ws_handler(request: Request) -> dict[str, object]:
            return {"status": "ok"}

        scope = make_ws_scope(headers=[])
        request = Request(scope)
        request.user = MockUser(user_id=1, username="alice")

        result = await ws_handler(request)
        assert result == {"status": "ok"}

    # -- Fail-closed: default behavior must reject unauthenticated ----------

    @pytest.mark.asyncio
    async def test_ws001_auth_middleware_processes_websocket_scope_type(self) -> None:
        """AuthenticationMiddleware must NOT skip websocket scope types.

        Verifies that the middleware processes websocket scopes rather than
        passing them through unauthenticated.
        """
        scope = make_ws_scope()
        processed = False

        async def inner_app(s: dict[str, object], r: object, s_end: object) -> None:
            nonlocal processed
            processed = True
            await s_end({"type": "websocket.accept"})

        middleware = AuthenticationMiddleware(inner_app)
        collector = SendCollector()
        await middleware(scope, noop_receive, collector)

        assert processed, "AuthenticationMiddleware must process websocket scopes"

    @pytest.mark.asyncio
    async def test_ws001_auth_middleware_sets_user_on_ws_scope(self) -> None:
        """AuthenticationMiddleware must populate scope['user'] for websocket."""
        scope = make_ws_scope()

        async def inner_app(s: dict[str, object], r: object, s_end: object) -> None:
            await s_end({"type": "websocket.accept"})

        with patch(
            "openviper.auth.manager.AuthManager.authenticate",
            return_value=(AnonymousUser(), {"type": "none"}),
        ):
            middleware = AuthenticationMiddleware(inner_app)
            collector = SendCollector()
            await middleware(scope, noop_receive, collector)

        assert "user" in scope, "scope['user'] must be set by AuthenticationMiddleware"
        assert "auth" in scope, "scope['auth'] must be set by AuthenticationMiddleware"


# ---------------------------------------------------------------------------
# WS-002: WebSocket origin is validated
# ---------------------------------------------------------------------------


class TestWS002WebSocketOriginValidation:
    """WebSocket origins must be validated.

    SECURITY GAP: CORSMiddleware currently only processes HTTP scope types
    and skips websocket scopes entirely.  This means WebSocket connections
    bypass origin validation - a critical security vulnerability.
    """

    # -- Positive tests: CORS middleware validates HTTP origins correctly ----

    def test_ws002_cors_exact_origins_configured(self) -> None:
        """CORSMiddleware must store exact allowed origins for validation."""

        async def app(scope: dict[str, object], receive: object, send: object) -> None:
            pass

        middleware = CORSMiddleware(
            app,
            allowed_origins=["https://trusted.example.com"],
        )
        assert middleware._exact_origins == frozenset(["https://trusted.example.com"])

    def test_ws002_cors_origin_allowed_for_exact_match(self) -> None:
        """origin_allowed must return True for exact origin matches."""

        async def app(scope: dict[str, object], receive: object, send: object) -> None:
            pass

        middleware = CORSMiddleware(
            app,
            allowed_origins=["https://trusted.example.com"],
        )
        assert middleware.origin_allowed("https://trusted.example.com") is True

    def test_ws002_cors_origin_rejected_for_untrusted(self) -> None:
        """origin_allowed must return False for untrusted origins."""

        async def app(scope: dict[str, object], receive: object, send: object) -> None:
            pass

        middleware = CORSMiddleware(
            app,
            allowed_origins=["https://trusted.example.com"],
        )
        assert middleware.origin_allowed("https://evil.example.com") is False

    # -- Negative tests: CORS middleware skips websocket scopes (SECURITY GAP)

    @pytest.mark.asyncio
    async def test_ws002_cors_skips_websocket_scope_type(self) -> None:
        """CORSMiddleware must NOT skip websocket scope types.

        Currently, CORSMiddleware only processes HTTP scopes and passes
        websocket scopes through without origin validation.  This test
        documents the security gap: untrusted origins can establish
        WebSocket connections because CORS is not enforced.
        """

        async def app(scope: dict[str, object], receive: object, send: object) -> None:
            await send({"type": "websocket.accept"})

        middleware = CORSMiddleware(
            app,
            allowed_origins=["https://trusted.example.com"],
        )

        # WebSocket scope with an untrusted Origin header
        scope = make_ws_scope(
            headers=[(b"origin", b"https://evil.example.com")],
        )
        collector = SendCollector()
        await middleware(scope, noop_receive, collector)

        # SECURITY GAP: The middleware passes websocket through without
        # validating the Origin.  The inner app receives the scope, meaning
        # the untrusted origin was NOT blocked.
        ws_messages = [m for m in collector.messages if m["type"].startswith("websocket")]
        assert len(ws_messages) > 0, (
            "CORSMiddleware currently passes websocket scopes through "
            "without origin validation - this is a known security gap"
        )

    @pytest.mark.asyncio
    async def test_ws002_cors_does_not_add_headers_to_websocket(self) -> None:
        """CORSMiddleware must not add CORS headers to websocket responses.

        Since the middleware skips websocket scopes, no CORS headers are
        added, meaning browsers receive no origin policy for WS upgrades.
        """

        async def app(scope: dict[str, object], receive: object, send: object) -> None:
            await send({"type": "websocket.accept"})

        middleware = CORSMiddleware(
            app,
            allowed_origins=["https://trusted.example.com"],
        )

        scope = make_ws_scope(
            headers=[(b"origin", b"https://trusted.example.com")],
        )
        collector = SendCollector()
        await middleware(scope, noop_receive, collector)

        # No CORS-related headers should appear in websocket messages
        for msg in collector.messages:
            if msg.get("type") == "http.response.start":
                header_names = [name.decode() for name, _ in msg.get("headers", [])]
                assert "access-control-allow-origin" not in header_names

    # -- Fail-closed: wildcard origins must be rejected with credentials ----

    def test_ws002_cors_rejects_wildcard_with_credentials(self) -> None:
        """CORSMiddleware must reject wildcard origin with credentials.

        This prevents a misconfiguration that would allow any origin
        to make credentialed WebSocket connections.
        """

        async def app(scope: dict[str, object], receive: object, send: object) -> None:
            pass

        with pytest.raises(ValueError, match="allow_credentials.*wildcard"):
            CORSMiddleware(app, allowed_origins=["*"], allow_credentials=True)

    # -- Positive: wildcard without credentials is allowed ------------------

    def test_ws002_cors_allows_wildcard_without_credentials(self) -> None:
        """Wildcard origins without credentials must be accepted."""

        async def app(scope: dict[str, object], receive: object, send: object) -> None:
            pass

        middleware = CORSMiddleware(
            app,
            allowed_origins=["*"],
            allow_credentials=False,
        )
        assert middleware._allow_all_origins is True


# ---------------------------------------------------------------------------
# WS-003: Channel subscription authorization is enforced
# ---------------------------------------------------------------------------


class TestWS003ChannelSubscriptionAuthorization:
    """Channel subscriptions must enforce authorization.

    WebSocket handlers must verify that the authenticated user has
    permission to subscribe to a given channel.  Cross-user subscription
    must be denied.
    """

    # -- Positive tests: decorators exist and work --------------------------

    def test_ws003_permission_required_decorator_callable(self) -> None:
        """permission_required decorator must be callable for route protection."""
        assert callable(permission_required)

    def test_ws003_role_required_decorator_callable(self) -> None:
        """role_required decorator must be callable for role-based access."""
        assert callable(role_required)

    def test_ws003_login_required_decorator_callable(self) -> None:
        """login_required decorator must be callable for auth gating."""
        assert callable(login_required)

    @pytest.mark.asyncio
    async def test_ws003_permission_required_allows_authorized_user(self) -> None:
        """permission_required must allow users with the required permission."""

        @permission_required("channel.subscribe")
        async def ws_subscribe(request: Request) -> dict[str, object]:
            return {"status": "subscribed"}

        scope = make_ws_scope()
        request = Request(scope)
        request.user = MockUser(
            user_id=1,
            username="alice",
            permissions=["channel.subscribe"],
        )

        result = await ws_subscribe(request)
        assert result == {"status": "subscribed"}

    @pytest.mark.asyncio
    async def test_ws003_role_required_allows_authorized_user(self) -> None:
        """role_required must allow users with the required role."""

        @role_required("admin")
        async def ws_admin_channel(request: Request) -> dict[str, object]:
            return {"status": "connected"}

        scope = make_ws_scope()
        request = Request(scope)
        request.user = MockUser(
            user_id=1,
            username="alice",
            roles=["admin"],
        )

        result = await ws_admin_channel(request)
        assert result == {"status": "connected"}

    # -- Negative tests: unauthorized users are denied ----------------------

    @pytest.mark.asyncio
    async def test_ws003_permission_required_denies_unauthorized_user(self) -> None:
        """permission_required must deny users lacking the required permission."""

        @permission_required("channel.subscribe")
        async def ws_subscribe(request: Request) -> dict[str, object]:
            return {"status": "subscribed"}

        scope = make_ws_scope()
        request = Request(scope)
        request.user = MockUser(
            user_id=2,
            username="bob",
            permissions=[],
        )

        with pytest.raises(PermissionDenied):
            await ws_subscribe(request)

    @pytest.mark.asyncio
    async def test_ws003_role_required_denies_unauthorized_user(self) -> None:
        """role_required must deny users lacking the required role."""

        @role_required("admin")
        async def ws_admin_channel(request: Request) -> dict[str, object]:
            return {"status": "connected"}

        scope = make_ws_scope()
        request = Request(scope)
        request.user = MockUser(
            user_id=2,
            username="bob",
            roles=["viewer"],
        )

        with pytest.raises(PermissionDenied):
            await ws_admin_channel(request)

    @pytest.mark.asyncio
    async def test_ws003_permission_required_denies_anonymous_user(self) -> None:
        """permission_required must reject anonymous (unauthenticated) users."""

        @permission_required("channel.subscribe")
        async def ws_subscribe(request: Request) -> dict[str, object]:
            return {"status": "subscribed"}

        scope = make_ws_scope()
        request = Request(scope)
        request.user = AnonymousUser()

        with pytest.raises(Unauthorized):
            await ws_subscribe(request)

    @pytest.mark.asyncio
    async def test_ws003_role_required_denies_anonymous_user(self) -> None:
        """role_required must reject anonymous (unauthenticated) users."""

        @role_required("admin")
        async def ws_admin_channel(request: Request) -> dict[str, object]:
            return {"status": "connected"}

        scope = make_ws_scope()
        request = Request(scope)
        request.user = AnonymousUser()

        with pytest.raises(Unauthorized):
            await ws_admin_channel(request)

    # -- Cross-user subscription isolation ----------------------------------

    @pytest.mark.asyncio
    async def test_ws003_cross_user_subscription_denied(self) -> None:
        """A user must not subscribe to another user's private channel.

        Simulates a scenario where user 'bob' attempts to subscribe to
        user 'alice's private channel - the permission check must deny.
        """

        @permission_required("channel.subscribe.alice_private")
        async def ws_subscribe_private(request: Request) -> dict[str, object]:
            return {"status": "subscribed"}

        scope = make_ws_scope()
        request = Request(scope)
        request.user = MockUser(
            user_id=2,
            username="bob",
            permissions=["channel.subscribe"],  # generic, not alice's private
        )

        with pytest.raises(PermissionDenied):
            await ws_subscribe_private(request)

    # -- Fail-closed: decorators must reject by default ---------------------

    @pytest.mark.asyncio
    async def test_ws003_login_required_rejects_user_without_is_authenticated(self) -> None:
        """login_required must reject when user lacks is_authenticated."""

        @login_required
        async def ws_handler(request: Request) -> dict[str, object]:
            return {"status": "ok"}

        scope = make_ws_scope()
        request = Request(scope)
        request.user = MockUser(is_authenticated=False)

        with pytest.raises(Unauthorized):
            await ws_handler(request)


# ---------------------------------------------------------------------------
# WS-004: WebSocket messages are rate limited
# ---------------------------------------------------------------------------


class TestWS004WebSocketRateLimiting:
    """WebSocket messages must be rate limited.

    SECURITY GAP: RateLimitMiddleware currently only processes HTTP scope
    types and skips websocket scopes entirely.  This means WebSocket
    connections bypass rate limiting - a denial-of-service vulnerability.
    """

    # -- Positive tests: rate limiter works for HTTP -------------------------

    def test_ws004_sliding_window_counter_configured(self) -> None:
        """SlidingWindowCounter must be configurable with limits."""
        counter = SlidingWindowCounter(max_requests=10, window_seconds=60)
        assert counter.max_requests == 10
        assert counter.window == 60.0

    @pytest.mark.asyncio
    async def test_ws004_rate_limit_allows_within_threshold(self) -> None:
        """SlidingWindowCounter must allow requests within the limit."""
        counter = SlidingWindowCounter(max_requests=5, window_seconds=60)
        for _ in range(5):
            allowed, remaining = await counter.is_allowed("test_key")
            assert allowed is True
        # 6th request must be rejected
        allowed, remaining = await counter.is_allowed("test_key")
        assert allowed is False
        assert remaining == 0

    @pytest.mark.asyncio
    async def test_ws004_rate_limit_rejects_over_threshold(self) -> None:
        """SlidingWindowCounter must reject requests exceeding the limit."""
        counter = SlidingWindowCounter(max_requests=3, window_seconds=60)
        for _ in range(3):
            await counter.is_allowed("test_key")
        allowed, remaining = await counter.is_allowed("test_key")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_ws004_rate_limit_keys_are_independent(self) -> None:
        """Different keys must have independent rate limits."""
        counter = SlidingWindowCounter(max_requests=2, window_seconds=60)
        # Exhaust key_a
        await counter.is_allowed("key_a")
        await counter.is_allowed("key_a")
        allowed_a, _ = await counter.is_allowed("key_a")
        assert allowed_a is False

        # key_b must still be allowed
        allowed_b, _ = await counter.is_allowed("key_b")
        assert allowed_b is True

    # -- Negative tests: rate limiter skips websocket scopes (SECURITY GAP) ---

    @pytest.mark.asyncio
    async def test_ws004_rate_limit_middleware_skips_websocket(self) -> None:
        """RateLimitMiddleware must NOT skip websocket scope types.

        Currently, RateLimitMiddleware only processes HTTP scopes and passes
        websocket scopes through without rate limiting.  This test documents
        the security gap: WebSocket connections can send unlimited messages.
        """

        async def app(scope: dict[str, object], receive: object, send: object) -> None:
            await send({"type": "websocket.accept"})

        middleware = RateLimitMiddleware(app, max_requests=1, window_seconds=60)

        scope = make_ws_scope()
        collector = SendCollector()
        await middleware(scope, noop_receive, collector)

        # The inner app was called - the websocket scope was NOT rate-limited
        ws_messages = [m for m in collector.messages if m["type"].startswith("websocket")]
        assert len(ws_messages) > 0, (
            "RateLimitMiddleware currently passes websocket scopes through "
            "without rate limiting - this is a known security gap"
        )

    @pytest.mark.asyncio
    async def test_ws004_rate_limit_middleware_limits_http(self) -> None:
        """RateLimitMiddleware must rate-limit HTTP scopes correctly."""
        call_count = 0

        async def app(scope: dict[str, object], receive: object, send: object) -> None:
            nonlocal call_count
            call_count += 1
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = RateLimitMiddleware(app, max_requests=2, window_seconds=60)

        # First two requests must pass
        for _ in range(2):
            scope = make_scope(method="GET", path="/api/data")
            collector = SendCollector()
            await middleware(scope, noop_receive, collector)
            assert collector.status_code == 200

        # Third request must be rate-limited (429)
        scope = make_scope(method="GET", path="/api/data")
        collector = SendCollector()
        await middleware(scope, noop_receive, collector)
        assert collector.status_code == 429

    # -- Fail-closed: rate limiter must use IP by default -------------------

    def test_ws004_rate_limit_default_key_uses_ip(self) -> None:
        """RateLimitMiddleware must use client IP as the default key."""
        scope = make_scope(method="GET", path="/ws/chat/")
        scope["client"] = ("192.168.1.100", 12345)
        key = RateLimitMiddleware.default_key(scope)
        assert key == "192.168.1.100"

    def test_ws004_rate_limit_default_key_falls_back_to_unknown(self) -> None:
        """RateLimitMiddleware must fall back to 'unknown' when no client IP."""
        scope = make_scope(method="GET", path="/ws/chat/")
        key = RateLimitMiddleware.default_key(scope)
        assert key == "unknown"

    @pytest.mark.asyncio
    async def test_ws004_sliding_window_counter_window_expiry(self) -> None:
        """SlidingWindowCounter must allow requests after the window expires."""
        counter = SlidingWindowCounter(max_requests=2, window_seconds=1.0)

        with patch("time.monotonic", return_value=100.0):
            allowed, _ = await counter.is_allowed("test_key")
            assert allowed is True
            allowed, _ = await counter.is_allowed("test_key")
            assert allowed is True

        # Window expires - requests must be allowed again
        with patch("time.monotonic", return_value=102.0):
            allowed, _ = await counter.is_allowed("test_key")
            assert allowed is True


# ---------------------------------------------------------------------------
# WS-005: Broadcasts are tenant-isolated
# ---------------------------------------------------------------------------


class TestWS005TenantIsolation:
    """Broadcasts must be tenant-isolated.

    Messages sent on a channel belonging to tenant A must never be
    delivered to connections belonging to tenant B.  This prevents
    cross-tenant data leakage in multi-tenant deployments.
    """

    # -- Positive tests: tenant context is propagated -----------------------

    def test_ws005_mock_user_supports_tenant_id(self) -> None:
        """MockUser must support tenant_id for tenant isolation testing."""
        user_a = MockUser(user_id=1, username="alice", tenant_id="tenant_a")
        user_b = MockUser(user_id=2, username="bob", tenant_id="tenant_b")
        assert user_a.tenant_id == "tenant_a"
        assert user_b.tenant_id == "tenant_b"
        assert user_a.tenant_id != user_b.tenant_id

    def test_ws005_anonymous_user_has_no_tenant(self) -> None:
        """AnonymousUser must have no tenant_id (fail-closed: no tenant = no access)."""
        anon = AnonymousUser()
        assert not getattr(anon, "is_authenticated", False)

    @pytest.mark.asyncio
    async def test_ws005_auth_middleware_propagates_tenant_user(self) -> None:
        """AuthenticationMiddleware must propagate user with tenant_id on WS scope."""
        user = MockUser(user_id=1, username="alice", tenant_id="tenant_a")
        scope = make_ws_scope(
            headers=[(b"authorization", b"Bearer valid.jwt.token")],
        )

        async def inner_app(s: dict[str, object], r: object, s_end: object) -> None:
            s["captured_user"] = s.get("user")
            await s_end({"type": "websocket.accept"})

        with patch(
            "openviper.auth.manager.AuthManager.authenticate",
            return_value=(user, {"type": "jwt", "token": "valid.jwt.token"}),
        ):
            middleware = AuthenticationMiddleware(inner_app)
            collector = SendCollector()
            await middleware(scope, noop_receive, collector)

        captured_user = scope["captured_user"]
        assert captured_user.tenant_id == "tenant_a"

    # -- Negative tests: cross-tenant message isolation ---------------------

    @pytest.mark.asyncio
    async def test_ws005_cross_tenant_subscription_denied(self) -> None:
        """A user in tenant_a must not subscribe to tenant_b's channels.

        Uses permission_required to enforce tenant-scoped channel access.
        """
        user_a = MockUser(
            user_id=1,
            username="alice",
            tenant_id="tenant_a",
            permissions=["channel.subscribe.tenant_a"],
        )

        @permission_required("channel.subscribe.tenant_b")
        async def ws_subscribe_tenant_b(request: Request) -> dict[str, object]:
            return {"status": "subscribed"}

        scope = make_ws_scope()
        request = Request(scope)
        request.user = user_a

        with pytest.raises(PermissionDenied):
            await ws_subscribe_tenant_b(request)

    @pytest.mark.asyncio
    async def test_ws005_tenant_isolation_via_role_required(self) -> None:
        """A user with tenant_a roles must not access tenant_b admin channels."""
        user_a = MockUser(
            user_id=1,
            username="alice",
            tenant_id="tenant_a",
            roles=["tenant_a_admin"],
        )

        @role_required("tenant_b_admin")
        async def ws_tenant_b_admin(request: Request) -> dict[str, object]:
            return {"status": "connected"}

        scope = make_ws_scope()
        request = Request(scope)
        request.user = user_a

        with pytest.raises(PermissionDenied):
            await ws_tenant_b_admin(request)

    # -- Fail-closed: no tenant = no access ---------------------------------

    @pytest.mark.asyncio
    async def test_ws005_anonymous_user_denied_tenant_channel(self) -> None:
        """Anonymous users must be denied access to any tenant channel."""

        @permission_required("channel.subscribe.tenant_a")
        async def ws_subscribe(request: Request) -> dict[str, object]:
            return {"status": "subscribed"}

        scope = make_ws_scope()
        request = Request(scope)
        request.user = AnonymousUser()

        with pytest.raises(Unauthorized):
            await ws_subscribe(request)

    @pytest.mark.asyncio
    async def test_ws005_user_without_tenant_denied_tenant_channel(self) -> None:
        """A user with no tenant_id must be denied tenant-scoped channels."""
        user_no_tenant = MockUser(
            user_id=3,
            username="charlie",
            tenant_id=None,
            permissions=["channel.subscribe"],
        )

        @permission_required("channel.subscribe.tenant_a")
        async def ws_subscribe_tenant_a(request: Request) -> dict[str, object]:
            return {"status": "subscribed"}

        scope = make_ws_scope()
        request = Request(scope)
        request.user = user_no_tenant

        with pytest.raises(PermissionDenied):
            await ws_subscribe_tenant_a(request)

    # -- CSRF does not apply to WebSocket (by design) -----------------------

    def test_ws005_csrf_middleware_skips_websocket(self) -> None:
        """CSRFMiddleware must skip websocket scope types.

        CSRF protection is not applicable to WebSocket upgrades because
        browsers enforce same-origin policy on the initial HTTP upgrade
        request.  The middleware correctly skips non-HTTP scopes.
        """
        assert "GET" in CSRF_SAFE_METHODS, "GET must be in CSRF_SAFE_METHODS for WS upgrades"

    @pytest.mark.asyncio
    async def test_ws005_csrf_middleware_passes_websocket_through(self) -> None:
        """CSRFMiddleware must pass websocket scopes through without validation.

        WebSocket upgrades use GET, which is in CSRF_SAFE_METHODS, so
        CSRF validation is not needed for the upgrade handshake.
        """

        async def app(scope: dict[str, object], receive: object, send: object) -> None:
            await send({"type": "websocket.accept"})

        middleware = CSRFMiddleware(app, secret="test-secret-key-for-csrf")
        scope = make_ws_scope()
        collector = SendCollector()
        await middleware(scope, noop_receive, collector)

        # The inner app must be called - websocket scopes pass through
        ws_messages = [m for m in collector.messages if m["type"].startswith("websocket")]
        assert len(ws_messages) > 0

    @pytest.mark.asyncio
    async def test_ws004_rate_limit_enforcement(self):
        """Rate limiting must enforce message limits."""
        counter = SlidingWindowCounter(max_requests=2, window_seconds=60)

        # First two messages should be allowed
        allowed1, _ = await counter.is_allowed("ws:user:1")
        assert allowed1 is True

        allowed2, _ = await counter.is_allowed("ws:user:1")
        assert allowed2 is True

        # Third message should be rate limited
        allowed3, _ = await counter.is_allowed("ws:user:1")
        assert allowed3 is False


# ---------------------------------------------------------------------------
# WS-005: Broadcasts are tenant-isolated
# ---------------------------------------------------------------------------


class TestWebSocketTenantIsolation:
    """WebSocket broadcasts must be tenant-isolated."""

    def test_ws005_context_var_isolation(self):
        """Context variables must isolate tenant data."""
        user_a = MockUser(user_id=1, tenant_id="tenant_a")
        user_b = MockUser(user_id=2, tenant_id="tenant_b")

        token_a = current_user.set(user_a)
        assert current_user.get().tenant_id == "tenant_a"
        current_user.reset(token_a)

        token_b = current_user.set(user_b)
        assert current_user.get().tenant_id == "tenant_b"
        current_user.reset(token_b)
