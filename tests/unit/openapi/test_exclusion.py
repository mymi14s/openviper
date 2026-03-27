"""Unit tests for OpenAPI exclusion — filter_openapi_routes and should_register_openapi."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    import pytest

from openviper.openapi.router import should_register_openapi
from openviper.openapi.schema import filter_openapi_routes, reset_openapi_cache
from openviper.routing.router import Route

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_route(path: str) -> Route:
    async def handler() -> None:
        pass

    return Route(path=path, methods={"GET"}, handler=handler)


# ---------------------------------------------------------------------------
# filter_openapi_routes
# ---------------------------------------------------------------------------


class TestFilterOpenApiRoutesNoExclusion:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_empty_exclude_list_returns_all_routes(self) -> None:
        routes = [_make_route("/users"), _make_route("/posts")]
        with patch("openviper.openapi.schema.settings") as mock_settings:
            mock_settings.OPENAPI_EXCLUDE = []
            result = filter_openapi_routes(routes)
        assert result == routes

    def test_missing_setting_attribute_returns_all_routes(self) -> None:
        routes = [_make_route("/users")]
        with patch("openviper.openapi.schema.settings") as mock_settings:
            del mock_settings.OPENAPI_EXCLUDE
            result = filter_openapi_routes(routes)
        assert result == routes

    def test_returns_new_list_not_same_object(self) -> None:
        routes = [_make_route("/users")]
        with patch("openviper.openapi.schema.settings") as mock_settings:
            mock_settings.OPENAPI_EXCLUDE = []
            result = filter_openapi_routes(routes)
        assert result is not routes


class TestFilterOpenApiRoutesDisableAll:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_all_sentinel_returns_empty_list(self) -> None:
        routes = [_make_route("/users"), _make_route("/admin/users")]
        with patch("openviper.openapi.schema.settings") as mock_settings:
            mock_settings.OPENAPI_EXCLUDE = "__ALL__"
            result = filter_openapi_routes(routes)
        assert result == []

    def test_all_sentinel_with_no_routes_returns_empty_list(self) -> None:
        with patch("openviper.openapi.schema.settings") as mock_settings:
            mock_settings.OPENAPI_EXCLUDE = "__ALL__"
            result = filter_openapi_routes([])
        assert result == []


class TestFilterOpenApiRoutesAdminExcluded:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_admin_routes_removed(self) -> None:
        routes = [
            _make_route("/users"),
            _make_route("/admin/dashboard"),
            _make_route("/admin/users"),
        ]
        with patch("openviper.openapi.schema.settings") as mock_settings:
            mock_settings.OPENAPI_EXCLUDE = ["admin"]
            result = filter_openapi_routes(routes)
        paths = [r.path for r in result]
        assert "/users" in paths
        assert "/admin/dashboard" not in paths
        assert "/admin/users" not in paths

    def test_admin_exact_match_removed(self) -> None:
        routes = [_make_route("/admin"), _make_route("/administrators")]
        with patch("openviper.openapi.schema.settings") as mock_settings:
            mock_settings.OPENAPI_EXCLUDE = ["admin"]
            result = filter_openapi_routes(routes)
        paths = [r.path for r in result]
        assert "/admin" not in paths
        assert "/administrators" in paths

    def test_non_admin_routes_preserved(self) -> None:
        routes = [_make_route("/users"), _make_route("/posts/{id:int}")]
        with patch("openviper.openapi.schema.settings") as mock_settings:
            mock_settings.OPENAPI_EXCLUDE = ["admin"]
            result = filter_openapi_routes(routes)
        assert len(result) == 2


class TestFilterOpenApiRoutesMultiplePrefixExcluded:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_multiple_prefixes_all_removed(self) -> None:
        routes = [
            _make_route("/users"),
            _make_route("/admin/settings"),
            _make_route("/blogs/post"),
            _make_route("/internal/health"),
        ]
        with patch("openviper.openapi.schema.settings") as mock_settings:
            mock_settings.OPENAPI_EXCLUDE = ["admin", "blogs", "internal"]
            result = filter_openapi_routes(routes)
        paths = [r.path for r in result]
        assert paths == ["/users"]

    def test_partial_overlap_not_excluded(self) -> None:
        routes = [
            _make_route("/blogs"),
            _make_route("/blogsearch"),
            _make_route("/blog"),
        ]
        with patch("openviper.openapi.schema.settings") as mock_settings:
            mock_settings.OPENAPI_EXCLUDE = ["blogs"]
            result = filter_openapi_routes(routes)
        paths = [r.path for r in result]
        assert "/blogs" not in paths
        assert "/blogsearch" in paths
        assert "/blog" in paths

    def test_case_insensitive_prefix_matching(self) -> None:
        routes = [_make_route("/Admin/panel"), _make_route("/users")]
        with patch("openviper.openapi.schema.settings") as mock_settings:
            mock_settings.OPENAPI_EXCLUDE = ["admin"]
            result = filter_openapi_routes(routes)
        paths = [r.path for r in result]
        assert "/Admin/panel" not in paths
        assert "/users" in paths

    def test_prefix_with_leading_slash_normalised(self) -> None:
        routes = [_make_route("/admin/panel"), _make_route("/users")]
        with patch("openviper.openapi.schema.settings") as mock_settings:
            mock_settings.OPENAPI_EXCLUDE = ["/admin"]
            result = filter_openapi_routes(routes)
        paths = [r.path for r in result]
        assert "/admin/panel" not in paths
        assert "/users" in paths


class TestFilterOpenApiRoutesInvalidSetting:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_invalid_non_list_non_string_falls_back_to_no_exclusion(self) -> None:
        routes = [_make_route("/users"), _make_route("/admin/panel")]
        with patch("openviper.openapi.schema.settings") as mock_settings:
            mock_settings.OPENAPI_EXCLUDE = 42
            result = filter_openapi_routes(routes)
        assert len(result) == 2

    def test_invalid_setting_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        routes = [_make_route("/users")]
        with patch("openviper.openapi.schema.settings") as mock_settings:
            mock_settings.OPENAPI_EXCLUDE = {"bad": "value"}
            with caplog.at_level(logging.WARNING, logger="openviper.openapi.schema"):
                filter_openapi_routes(routes)
        assert any("unexpected value" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# should_register_openapi
# ---------------------------------------------------------------------------


class TestShouldRegisterOpenapi:
    def test_returns_true_when_enabled_and_no_exclusion(self) -> None:
        with patch("openviper.openapi.router.settings") as mock_settings:
            mock_settings.OPENAPI_ENABLED = True
            mock_settings.OPENAPI_EXCLUDE = []
            assert should_register_openapi() is True

    def test_returns_false_when_openapi_enabled_false(self) -> None:
        with patch("openviper.openapi.router.settings") as mock_settings:
            mock_settings.OPENAPI_ENABLED = False
            mock_settings.OPENAPI_EXCLUDE = []
            assert should_register_openapi() is False

    def test_returns_false_when_exclude_is_all(self) -> None:
        with patch("openviper.openapi.router.settings") as mock_settings:
            mock_settings.OPENAPI_ENABLED = True
            mock_settings.OPENAPI_EXCLUDE = "__ALL__"
            assert should_register_openapi() is False

    def test_returns_true_when_exclude_is_prefix_list(self) -> None:
        with patch("openviper.openapi.router.settings") as mock_settings:
            mock_settings.OPENAPI_ENABLED = True
            mock_settings.OPENAPI_EXCLUDE = ["admin", "blogs"]
            assert should_register_openapi() is True

    def test_returns_true_when_exclude_not_set(self) -> None:
        with patch("openviper.openapi.router.settings") as mock_settings:
            mock_settings.OPENAPI_ENABLED = True
            del mock_settings.OPENAPI_EXCLUDE
            assert should_register_openapi() is True
