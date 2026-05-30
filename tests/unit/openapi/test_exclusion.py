"""Unit tests for OpenAPI exclusion - filter_openapi_routes and should_register_openapi."""

from __future__ import annotations

import logging
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


def make_route(path: str) -> Route:
    async def handler() -> None:
        pass

    return Route(path=path, methods={"GET"}, handler=handler)


def openapi_cfg(
    exclude: list[str] | str | None = None,
    admin_url: str | None = None,
    enabled: bool = True,
) -> dict[str, object]:
    """Build a minimal OPENAPI dict for test patching."""
    cfg: dict[str, object] = {
        "title": "OpenViper API",
        "version": "0.0.1",
        "description": "",
        "docs_url": "/open-api/docs",
        "redoc_url": "/open-api/redoc",
        "schema_url": "/open-api/openapi.json",
        "enabled": enabled,
        "admin_url": admin_url,
        "exclude": exclude if exclude is not None else [],
    }
    return cfg


# ---------------------------------------------------------------------------
# filter_openapi_routes
# ---------------------------------------------------------------------------


class TestFilterOpenApiRoutesNoExclusion:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_empty_exclude_list_returns_all_routes(self) -> None:
        routes = [make_route("/users"), make_route("/posts")]
        with patch("openviper.openapi.schema.read_openapi_settings", return_value=openapi_cfg()):
            result = filter_openapi_routes(routes)
        assert result == routes

    def test_missing_setting_attribute_returns_all_routes(self) -> None:
        routes = [make_route("/users")]
        with patch("openviper.openapi.schema.read_openapi_settings", return_value=openapi_cfg()):
            result = filter_openapi_routes(routes)
        assert result == routes

    def test_returns_new_list_not_same_object(self) -> None:
        routes = [make_route("/users")]
        with patch("openviper.openapi.schema.read_openapi_settings", return_value=openapi_cfg()):
            result = filter_openapi_routes(routes)
        assert result is not routes


class TestFilterOpenApiRoutesDefaultAdminExclusion:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_admin_routes_hidden_without_explicit_admin_url(self) -> None:
        routes = [make_route("/users"), make_route("/admin"), make_route("/admin/users")]
        with patch(
            "openviper.openapi.schema.read_openapi_settings",
            return_value=openapi_cfg(admin_url=None),
        ):
            result = filter_openapi_routes(routes)
        paths = [route.path for route in result]
        assert paths == ["/users"]

    def test_admin_routes_shown_when_admin_url_is_explicit(self) -> None:
        routes = [make_route("/users"), make_route("/admin"), make_route("/admin/users")]
        with patch(
            "openviper.openapi.schema.read_openapi_settings",
            return_value=openapi_cfg(admin_url="/admin"),
        ):
            result = filter_openapi_routes(routes)
        assert result == routes


class TestFilterOpenApiRoutesDisableAll:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_all_sentinel_returns_empty_list(self) -> None:
        routes = [make_route("/users"), make_route("/admin/users")]
        with patch(
            "openviper.openapi.schema.read_openapi_settings",
            return_value=openapi_cfg(exclude="__ALL__"),
        ):
            result = filter_openapi_routes(routes)
        assert result == []

    def test_all_sentinel_with_no_routes_returns_empty_list(self) -> None:
        with patch(
            "openviper.openapi.schema.read_openapi_settings",
            return_value=openapi_cfg(exclude="__ALL__"),
        ):
            result = filter_openapi_routes([])
        assert result == []


class TestFilterOpenApiRoutesAdminExcluded:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_admin_routes_removed(self) -> None:
        routes = [
            make_route("/users"),
            make_route("/admin/dashboard"),
            make_route("/admin/users"),
        ]
        with patch(
            "openviper.openapi.schema.read_openapi_settings",
            return_value=openapi_cfg(exclude=["admin"]),
        ):
            result = filter_openapi_routes(routes)
        paths = [r.path for r in result]
        assert "/users" in paths
        assert "/admin/dashboard" not in paths
        assert "/admin/users" not in paths

    def test_admin_exact_match_removed(self) -> None:
        routes = [make_route("/admin"), make_route("/administrators")]
        with patch(
            "openviper.openapi.schema.read_openapi_settings",
            return_value=openapi_cfg(exclude=["admin"]),
        ):
            result = filter_openapi_routes(routes)
        paths = [r.path for r in result]
        assert "/admin" not in paths
        assert "/administrators" in paths

    def test_non_admin_routes_preserved(self) -> None:
        routes = [make_route("/users"), make_route("/posts/{id:int}")]
        with patch(
            "openviper.openapi.schema.read_openapi_settings",
            return_value=openapi_cfg(exclude=["admin"]),
        ):
            result = filter_openapi_routes(routes)
        assert len(result) == 2


class TestFilterOpenApiRoutesMultiplePrefixExcluded:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_multiple_prefixes_all_removed(self) -> None:
        routes = [
            make_route("/users"),
            make_route("/admin/settings"),
            make_route("/blogs/post"),
            make_route("/internal/health"),
        ]
        with patch(
            "openviper.openapi.schema.read_openapi_settings",
            return_value=openapi_cfg(exclude=["admin", "blogs", "internal"]),
        ):
            result = filter_openapi_routes(routes)
        paths = [r.path for r in result]
        assert paths == ["/users"]

    def test_partial_overlap_not_excluded(self) -> None:
        routes = [
            make_route("/blogs"),
            make_route("/blogsearch"),
            make_route("/blog"),
        ]
        with patch(
            "openviper.openapi.schema.read_openapi_settings",
            return_value=openapi_cfg(exclude=["blogs"]),
        ):
            result = filter_openapi_routes(routes)
        paths = [r.path for r in result]
        assert "/blogs" not in paths
        assert "/blogsearch" in paths
        assert "/blog" in paths

    def test_case_insensitive_prefix_matching(self) -> None:
        routes = [make_route("/Admin/panel"), make_route("/users")]
        with patch(
            "openviper.openapi.schema.read_openapi_settings",
            return_value=openapi_cfg(exclude=["admin"]),
        ):
            result = filter_openapi_routes(routes)
        paths = [r.path for r in result]
        assert "/Admin/panel" not in paths
        assert "/users" in paths

    def test_prefix_with_leading_slash_normalised(self) -> None:
        routes = [make_route("/admin/panel"), make_route("/users")]
        with patch(
            "openviper.openapi.schema.read_openapi_settings",
            return_value=openapi_cfg(exclude=["/admin"]),
        ):
            result = filter_openapi_routes(routes)
        paths = [r.path for r in result]
        assert "/admin/panel" not in paths
        assert "/users" in paths


class TestFilterOpenApiRoutesInvalidSetting:
    def setup_method(self) -> None:
        reset_openapi_cache()

    def test_invalid_non_list_non_string_falls_back_to_no_exclusion(self) -> None:
        routes = [make_route("/users"), make_route("/admin/panel")]
        with patch(
            "openviper.openapi.schema.read_openapi_settings",
            return_value=openapi_cfg(exclude=42, admin_url="/admin"),
        ):
            result = filter_openapi_routes(routes)
        assert len(result) == 2

    def test_invalid_setting_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        routes = [make_route("/users")]
        with patch(
            "openviper.openapi.schema.read_openapi_settings",
            return_value=openapi_cfg(exclude={"bad": "value"}),
        ):
            with caplog.at_level(logging.WARNING, logger="openviper.openapi.schema"):
                filter_openapi_routes(routes)
        assert any("unexpected value" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# should_register_openapi
# ---------------------------------------------------------------------------


class TestShouldRegisterOpenapi:
    def test_returns_true_when_enabled_and_no_exclusion(self) -> None:
        with patch("openviper.openapi.router.settings") as mock_settings:
            mock_settings.OPENAPI = openapi_cfg(enabled=True, exclude=[])
            assert should_register_openapi() is True

    def test_returns_false_when_openapi_enabled_false(self) -> None:
        with patch("openviper.openapi.router.settings") as mock_settings:
            mock_settings.OPENAPI = openapi_cfg(enabled=False, exclude=[])
            assert should_register_openapi() is False

    def test_returns_false_when_exclude_is_all(self) -> None:
        with patch("openviper.openapi.router.settings") as mock_settings:
            mock_settings.OPENAPI = openapi_cfg(enabled=True, exclude="__ALL__")
            assert should_register_openapi() is False

    def test_returns_true_when_exclude_is_prefix_list(self) -> None:
        with patch("openviper.openapi.router.settings") as mock_settings:
            mock_settings.OPENAPI = openapi_cfg(enabled=True, exclude=["admin", "blogs"])
            assert should_register_openapi() is True

    def test_returns_true_when_exclude_not_set(self) -> None:
        with patch("openviper.openapi.router.settings") as mock_settings:
            mock_settings.OPENAPI = openapi_cfg(enabled=True, exclude=[])
            assert should_register_openapi() is True
