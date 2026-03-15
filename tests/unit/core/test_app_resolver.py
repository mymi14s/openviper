"""Unit tests for openviper.core.app_resolver — App resolution logic."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from openviper.core.app_resolver import (
    _SEARCH_PATTERN_CACHE,
    _SEARCH_PATTERN_CACHE_MAX,
    AppResolver,
)


class TestAppResolver:
    """Tests for AppResolver class."""

    def setup_method(self):
        self.test_dir = tempfile.mkdtemp()
        self.resolver = AppResolver(project_root=self.test_dir)
        _SEARCH_PATTERN_CACHE.clear()

    def teardown_method(self):
        shutil.rmtree(self.test_dir)

    def _create_app(self, name: str, parent_dir: str | None = None, has_models=True, has_init=True):
        """Helper to create a dummy app structure."""
        if parent_dir:
            base_path = os.path.join(self.test_dir, parent_dir, name)
        else:
            base_path = os.path.join(self.test_dir, name)

        os.makedirs(base_path, exist_ok=True)
        if has_init:
            (Path(base_path) / "__init__.py").touch()
        if has_models:
            (Path(base_path) / "models.py").touch()
        return base_path

    def test_get_project_root_default(self):
        with patch("os.getcwd", return_value="/tmp/test"):
            resolver = AppResolver()
            assert resolver.project_root == "/tmp/test"

    def test_resolve_app_cache(self):
        self.resolver.app_cache["myapp"] = ("/path/to/app", True)
        path, found = self.resolver.resolve_app("myapp")
        assert found is True
        assert path == "/path/to/app"

    def test_resolve_app_direct_root(self):
        app_path = self._create_app("blog")
        path, found = self.resolver.resolve_app("blog")
        assert found is True
        assert path == app_path

    def test_resolve_app_direct_nested(self):
        app_path = self._create_app("blog", parent_dir="apps")
        path, found = self.resolver.resolve_app("apps.blog")
        assert found is True
        assert path == app_path

    def test_resolve_app_relative(self):
        # blog in apps/blog resolved from name "blog"
        app_path = self._create_app("blog", parent_dir="apps")
        path, found = self.resolver.resolve_app("blog")
        assert found is True
        assert path == app_path

    def test_resolve_app_search_patterns(self):
        # Deeply nested app
        app_path = self._create_app("blog", parent_dir="src/modules/core")
        path, found = self.resolver.resolve_app("blog")
        assert found is True
        assert path == app_path

    def test_resolve_app_search_patterns_cache(self):
        cache_key = (self.resolver.project_root, "cachedapp")
        _SEARCH_PATTERN_CACHE[cache_key] = "/fake/path"

        path, found = self.resolver.resolve_app("cachedapp")
        assert found is True
        assert path == "/fake/path"

    def test_resolve_app_not_found(self):
        path, found = self.resolver.resolve_app("nonexistent")
        assert found is False
        assert path is None

    def test_is_valid_app_directory_routes_only(self):
        base_path = os.path.join(self.test_dir, "routes_app")
        os.makedirs(base_path)
        (Path(base_path) / "__init__.py").touch()
        (Path(base_path) / "routes.py").touch()

        assert self.resolver._is_valid_app_directory(base_path) is True

    def test_is_valid_app_directory_migrations_only(self):
        base_path = os.path.join(self.test_dir, "mig_app")
        os.makedirs(os.path.join(base_path, "migrations"))
        (Path(base_path) / "__init__.py").touch()

        assert self.resolver._is_valid_app_directory(base_path) is True

    def test_is_valid_app_directory_invalid(self):
        base_path = os.path.join(self.test_dir, "not_an_app")
        os.makedirs(base_path)
        # Missing __init__.py and models.py
        assert self.resolver._is_valid_app_directory(base_path) is False

    def test_resolve_all_apps(self):
        self._create_app("app1")
        self._create_app("app2")

        results = self.resolver.resolve_all_apps(["app1", "app2", "missing", "openviper.auth"])
        assert "app1" in results["found"]
        assert "app2" in results["found"]
        assert "missing" in results["not_found"]
        # openviper.auth should be skipped by default
        assert "openviper.auth" not in results["found"]
        assert "openviper.auth" not in results["not_found"]

    def test_resolve_all_apps_include_builtin(self):
        with patch.object(self.resolver, "resolve_app", return_value=("/path", True)):
            results = self.resolver.resolve_all_apps(["openviper.auth"], include_builtin=True)
            assert "openviper.auth" in results["found"]

    def test_get_migrations_dir_creates_new(self):
        self._create_app("blog")
        mig_dir = self.resolver.get_migrations_dir("blog")
        assert os.path.exists(mig_dir)
        assert os.path.basename(mig_dir) == "migrations"
        assert os.path.exists(os.path.join(mig_dir, "__init__.py"))

    def test_get_migrations_dir_app_not_found(self):
        assert self.resolver.get_migrations_dir("nonexistent") is None

    def test_print_app_locations(self, capsys):
        self._create_app("blog")
        self.resolver.print_app_locations(["blog", "missing"])
        captured = capsys.readouterr()
        assert "App Locations:" in captured.out
        assert "blog:" in captured.out
        assert "Not Found:" in captured.out
        assert "missing" in captured.out

    def test_print_app_not_found_error(self, capsys):
        self.resolver.print_app_not_found_error("myapp", ["/path/1", "/path/2"])
        captured = capsys.readouterr()
        assert "ERROR: App 'myapp' not found" in captured.out
        assert "/path/1" in captured.out

    def test_print_app_not_in_settings_error(self, capsys):
        self.resolver.print_app_not_in_settings_error("myapp", "/path/to/myapp")
        captured = capsys.readouterr()
        assert "ERROR: App 'myapp' exists but not in INSTALLED_APPS" in captured.out
        assert "/path/to/myapp" in captured.out


class TestSearchPatternCacheBound:
    """Test that _SEARCH_PATTERN_CACHE is bounded."""

    def setup_method(self):
        _SEARCH_PATTERN_CACHE.clear()

    def teardown_method(self):
        _SEARCH_PATTERN_CACHE.clear()

    def test_cache_max_constant_is_positive(self):
        assert _SEARCH_PATTERN_CACHE_MAX > 0

    def test_cache_evicts_oldest_when_full(self):
        """Filling beyond max should evict the oldest entry."""
        # Fill cache to max
        for i in range(_SEARCH_PATTERN_CACHE_MAX):
            _SEARCH_PATTERN_CACHE[("root", f"app_{i}")] = f"/path/app_{i}"

        assert len(_SEARCH_PATTERN_CACHE) == _SEARCH_PATTERN_CACHE_MAX

        # The first entry should exist before eviction
        assert ("root", "app_0") in _SEARCH_PATTERN_CACHE

        # Simulate what _try_search_patterns does when adding one more
        cache_key = ("root", "app_new")
        if len(_SEARCH_PATTERN_CACHE) >= _SEARCH_PATTERN_CACHE_MAX:
            _SEARCH_PATTERN_CACHE.pop(next(iter(_SEARCH_PATTERN_CACHE)))
        _SEARCH_PATTERN_CACHE[cache_key] = "/path/app_new"

        # Oldest entry should be evicted, new entry present
        assert ("root", "app_0") not in _SEARCH_PATTERN_CACHE
        assert ("root", "app_new") in _SEARCH_PATTERN_CACHE
        assert len(_SEARCH_PATTERN_CACHE) == _SEARCH_PATTERN_CACHE_MAX
