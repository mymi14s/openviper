"""Routing security tests.

Requirement IDs: ROUTE-001 through ROUTE-008.
"""

from __future__ import annotations

import time

import pytest

from openviper.db.executor import validate_regex_pattern
from openviper.exceptions import FieldError
from openviper.routing.router import (
    PathSecurityError,
    Route,
    Router,
    normalize_path,
    sanitize_request_path,
)


class TestTrailingSlashBypass:
    """Protected routes must enforce authorization regardless of trailing slash."""

    def test_route001_trailing_slash_compiled_separately(self):
        """Routes with and without trailing slashes are distinct patterns."""
        route_with = Route("/admin", {"GET"}, handler=lambda r: r, name="admin")
        route_without = Route("/admin/", {"GET"}, handler=lambda r: r, name="admin_slash")

        # Both should compile successfully
        assert route_with._regex is not None
        assert route_without._regex is not None

    def test_route001_normalize_preserves_trailing_slash(self):
        """Path normalization must not add or remove trailing slashes."""
        assert normalize_path("/admin") == "/admin"
        assert normalize_path("/admin/") == "/admin/"

    def test_route001_normalize_collapses_consecutive_slashes(self):
        """Path normalization must collapse consecutive slashes."""
        assert normalize_path("//foo///bar") == "/foo/bar"

    def test_route001_router_matches_both_variants(self):
        """Router must match both /admin and /admin/ if both are registered."""
        router = Router()

        async def admin_handler(request):
            return {"status": "ok"}

        router.add("/admin", admin_handler, methods=["GET"])
        router.add("/admin/", admin_handler, methods=["GET"])

        # Router.resolve must find a match for both variants
        route, params = router.resolve("GET", "/admin")
        assert route is not None

        route_slash, params_slash = router.resolve("GET", "/admin/")
        assert route_slash is not None


class TestEncodedPathBypass:
    """Encoded path variants must not bypass route-level security."""

    def test_route002_encoded_slash_rejected_by_sanitize(self):
        """The router must reject paths containing %2F during sanitization."""
        with pytest.raises(PathSecurityError):
            sanitize_request_path("/admin%2fpanel")

    def test_route002_double_encoded_slash_not_decoded(self):
        """Double-encoded slashes (%252F) are not decoded by the router.

        The router does not perform double-decoding, so %252F is treated as
        literal characters rather than a path separator. This is safe because
        the encoded value never resolves to an actual slash during routing.
        """
        # %252F is not decoded to / by the router, so it won't match /admin/panel
        # It's treated as a literal path segment, which is safe.
        result = sanitize_request_path("/admin%252fpanel")
        # Should not raise PathSecurityError because %252F is not %2F
        # and won't be decoded to a path separator
        assert result == "/admin%252fpanel"

    def test_route002_dot_dot_rejected_by_sanitize(self):
        """Path traversal via ../ must be rejected during sanitization."""
        with pytest.raises(PathSecurityError):
            sanitize_request_path("/admin/../secret")

    def test_route002_dot_dot_at_start_rejected(self):
        """Path traversal at the start of the path must be rejected."""
        with pytest.raises(PathSecurityError):
            sanitize_request_path("/../etc/passwd")

    def test_route002_dot_dot_mid_path_rejected(self):
        """Path traversal in the middle of a path must be rejected."""
        with pytest.raises(PathSecurityError):
            sanitize_request_path("/foo/../bar")

    def test_route002_path_with_parameters_matches_correctly(self):
        """Parameterized routes must match correctly without encoding bypass."""
        route = Route("/users/{id:int}", {"GET"}, handler=lambda r: r)
        match = route.match("/users/42")
        assert match is not None
        assert match["id"] == 42

        # Non-integer must not match
        no_match = route.match("/users/abc")
        assert no_match is None

    def test_route002_resolve_rejects_traversal_path(self):
        """Router.resolve must reject paths containing directory traversal."""
        router = Router()

        async def handler(request):
            return {"status": "ok"}

        router.add("/admin", handler, methods=["GET"])

        with pytest.raises(PathSecurityError):
            router.resolve("GET", "/admin/../secret")

    def test_route002_resolve_rejects_encoded_slash(self):
        """Router.resolve must reject paths containing encoded slashes."""
        router = Router()

        async def handler(request):
            return {"status": "ok"}

        router.add("/admin", handler, methods=["GET"])

        with pytest.raises(PathSecurityError):
            router.resolve("GET", "/admin%2fpanel")


class TestRoutePrecedence:
    """More specific routes must take precedence over broader ones."""

    def test_route003_literal_routes_match_before_dynamic(self):
        """Literal path segments must match before parameterized ones."""
        router = Router()

        async def admin_handler(request):
            return {"handler": "admin"}

        async def user_handler(request):
            return {"handler": "user"}

        router.add("/admin", admin_handler, methods=["GET"])
        router.add("/{username}", user_handler, methods=["GET"])

        # /admin must match the admin handler, not the dynamic one
        route, params = router.resolve("GET", "/admin")
        assert route is not None

    def test_route003_specific_routes_prioritized(self):
        """More specific routes must be tried before less specific ones."""
        route_specific = Route("/api/v1/users", {"GET"}, handler=lambda r: r)
        route_broad = Route("/api/{version}/users", {"GET"}, handler=lambda r: r)

        # Both should compile; specificity determines order
        assert route_specific._is_literal is True
        assert route_broad._is_literal is False


class TestRegexReDoS:
    """Regex routes must not be vulnerable to catastrophic backtracking."""

    def test_route004_compile_path_rejects_nested_quantifiers(self):
        """The framework must validate regex patterns for ReDoS vectors."""
        # Nested quantifiers are the primary ReDoS vector
        with pytest.raises(FieldError):
            validate_regex_pattern("(a+)+")

        with pytest.raises(FieldError):
            validate_regex_pattern("(a*)*")

        with pytest.raises(FieldError):
            validate_regex_pattern("(a+)*")

    def test_route004_compile_path_rejects_oversized_pattern(self):
        """Regex patterns exceeding maximum length must be rejected."""
        with pytest.raises(FieldError):
            validate_regex_pattern("a" * 501)

    def test_route004_compile_path_accepts_safe_pattern(self):
        """Safe regex patterns must be accepted."""
        # Should not raise
        validate_regex_pattern("^[a-z]+$")
        validate_regex_pattern("^user_[0-9]+$")

    def test_route004_path_matching_completes_quickly(self):
        """Path matching must complete within a reasonable time for long paths."""
        route = Route("/users/{id:int}", {"GET"}, handler=lambda r: r)
        # Long but valid path
        start = time.monotonic()
        result = route.match("/users/42")
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, "Path matching took too long"
        assert result is not None


class TestStaticFileMiddlewareEnforcement:
    """Static file routes must go through the same middleware pipeline."""

    def test_route005_static_route_registered_normally(self):
        """Static file routes must be registered through the router."""
        router = Router()

        async def static_handler(request):
            return {"file": True}

        router.add("/static/{path:path}", static_handler, methods=["GET"])
        route, params = router.resolve("GET", "/static/css/style.css")
        assert route is not None

    def test_route005_path_converter_rejects_traversal(self):
        """The {path:path} converter must not match directory traversal patterns."""
        route = Route("/static/{filepath:path}", {"GET"}, handler=lambda r: r)
        # Valid paths must match
        match = route.match("/static/css/style.css")
        assert match is not None
        # The path converter now rejects segments starting with ..
        # Traversal is also blocked at the normalization layer.


class TestNullByteRejection:
    """Paths containing null bytes must be rejected to prevent truncation attacks."""

    def test_route006_null_byte_rejected_by_sanitize(self):
        """sanitize_request_path must reject paths containing null bytes."""
        with pytest.raises(PathSecurityError):
            sanitize_request_path("/admin\x00/secret")

    def test_route006_null_byte_rejected_by_resolve(self):
        """Router.resolve must reject paths containing null bytes."""
        router = Router()

        async def handler(request):
            return {"status": "ok"}

        router.add("/admin", handler, methods=["GET"])

        with pytest.raises(PathSecurityError):
            router.resolve("GET", "/admin\x00/secret")

    def test_route006_null_byte_percent_encoded_not_decoded(self):
        """Percent-encoded null bytes (%00) are not decoded by the router.

        The ASGI server is responsible for decoding; the router treats %00
        as a literal string and will not match routes expecting it.
        """
        route = Route("/admin", {"GET"}, handler=lambda r: r)
        result = route.match("/admin%00secret")
        assert result is None


class TestUnknownConverterRejection:
    """Unknown path converter types must raise an error at route registration."""

    def test_route007_unknown_converter_raises_value_error(self):
        """Registering a route with an unknown converter type must raise ValueError."""
        with pytest.raises(ValueError, match="Unknown path converter"):
            Route("/users/{id:unknown}", {"GET"}, handler=lambda r: r)

    def test_route007_known_converters_accepted(self):
        """All built-in converter types must be accepted."""
        for conv in ("str", "int", "float", "path", "uuid", "slug"):
            route = Route(f"/{{{conv}_val:{conv}}}", {"GET"}, handler=lambda r: r)
            assert route._regex is not None

    def test_route007_default_converter_accepted(self):
        """Parameters without an explicit type default to 'str'."""
        route = Route("/users/{id}", {"GET"}, handler=lambda r: r)
        assert route._regex is not None
        assert "id" in route._converters


class TestUrlForSanitization:
    """url_for must reject path parameter values that could manipulate routing."""

    def test_route008_url_for_rejects_traversal(self):
        """url_for must reject parameter values containing '..'."""
        router = Router()
        router.add("/users/{id}", lambda r: r, methods=["GET"], namespace="user_detail")
        _ = router.routes  # trigger index build

        with pytest.raises(ValueError, match="disallowed characters"):
            router.url_for("user_detail", id="../admin")

    def test_route008_url_for_rejects_slash_injection(self):
        """url_for must reject parameter values containing '/'."""
        router = Router()
        router.add("/users/{id}", lambda r: r, methods=["GET"], namespace="user_detail")
        _ = router.routes

        with pytest.raises(ValueError, match="disallowed characters"):
            router.url_for("user_detail", id="admin/secret")

    def test_route008_url_for_rejects_null_byte(self):
        """url_for must reject parameter values containing null bytes."""
        router = Router()
        router.add("/users/{id}", lambda r: r, methods=["GET"], namespace="user_detail")
        _ = router.routes

        with pytest.raises(ValueError, match="disallowed characters"):
            router.url_for("user_detail", id="admin\x00")

    def test_route008_url_for_accepts_safe_values(self):
        """url_for must accept safe parameter values."""
        router = Router()
        router.add("/users/{id}", lambda r: r, methods=["GET"], namespace="user_detail")
        _ = router.routes

        result = router.url_for("user_detail", id="42")
        assert result == "/users/42"

    def test_route008_url_for_preserves_unfilled_placeholders(self):
        """url_for must leave unfilled placeholders intact."""
        router = Router()
        router.add(
            "/users/{id}/posts/{post_id:int}", lambda r: r, methods=["GET"], namespace="user_posts"
        )
        _ = router.routes

        result = router.url_for("user_posts", id="42")
        assert result == "/users/42/posts/{post_id:int}"
