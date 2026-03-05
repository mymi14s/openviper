"""Integration tests for openviper.core.app_resolver."""

from __future__ import annotations

import os

import pytest

from openviper.core.app_resolver import AppResolver

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary project with some fake app directories."""
    # A valid app: has __init__.py and models.py
    valid_app = tmp_path / "myapp"
    valid_app.mkdir()
    (valid_app / "__init__.py").touch()
    (valid_app / "models.py").touch()

    # An app with routes.py instead of models.py
    routes_app = tmp_path / "routesapp"
    routes_app.mkdir()
    (routes_app / "__init__.py").touch()
    (routes_app / "routes.py").touch()

    # An app with migrations dir
    migrations_app = tmp_path / "migapp"
    migrations_app.mkdir()
    (migrations_app / "__init__.py").touch()
    (migrations_app / "migrations").mkdir()

    # Not a valid app (no models/routes)
    not_app = tmp_path / "notapp"
    not_app.mkdir()
    (not_app / "__init__.py").touch()

    # Not a valid app (no __init__.py)
    no_init = tmp_path / "noinit"
    no_init.mkdir()
    (no_init / "models.py").touch()

    # App in a subdirectory (apps/subapp)
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    sub_app = apps_dir / "subapp"
    sub_app.mkdir()
    (sub_app / "__init__.py").touch()
    (sub_app / "models.py").touch()

    return tmp_path


# ---------------------------------------------------------------------------
# _is_valid_app_directory
# ---------------------------------------------------------------------------


class TestIsValidAppDirectory:
    def test_valid_with_models(self, temp_project):
        path = str(temp_project / "myapp")
        assert AppResolver._is_valid_app_directory(path) is True

    def test_valid_with_routes(self, temp_project):
        path = str(temp_project / "routesapp")
        assert AppResolver._is_valid_app_directory(path) is True

    def test_valid_with_migrations(self, temp_project):
        path = str(temp_project / "migapp")
        assert AppResolver._is_valid_app_directory(path) is True

    def test_missing_init_is_invalid(self, temp_project):
        path = str(temp_project / "noinit")
        assert AppResolver._is_valid_app_directory(path) is False

    def test_no_models_or_routes_is_invalid(self, temp_project):
        path = str(temp_project / "notapp")
        assert AppResolver._is_valid_app_directory(path) is False

    def test_nonexistent_path_is_invalid(self, temp_project):
        path = str(temp_project / "doesnotexist")
        assert AppResolver._is_valid_app_directory(path) is False

    def test_file_not_dir_is_invalid(self, tmp_path):
        f = tmp_path / "afile.txt"
        f.write_text("hello")
        assert AppResolver._is_valid_app_directory(str(f)) is False


# ---------------------------------------------------------------------------
# AppResolver.resolve_app - _try_direct_path
# ---------------------------------------------------------------------------


class TestResolveDirect:
    def test_direct_app_found(self, temp_project):
        resolver = AppResolver(project_root=str(temp_project))
        path, found = resolver.resolve_app("myapp")
        assert found is True
        assert path is not None
        assert "myapp" in path

    def test_dotted_path_found(self, temp_project):
        # apps.subapp -> apps/subapp exists and is valid
        resolver = AppResolver(project_root=str(temp_project))
        path, found = resolver.resolve_app("apps.subapp")
        assert found is True

    def test_nonexistent_app_not_found(self, temp_project):
        resolver = AppResolver(project_root=str(temp_project))
        path, found = resolver.resolve_app("nonexistent_xyz")
        assert found is False
        assert path is None


# ---------------------------------------------------------------------------
# AppResolver.resolve_app - _try_relative_path
# ---------------------------------------------------------------------------


class TestResolveRelative:
    def test_relative_path_finds_apps_subdirectory(self, temp_project):
        # "subapp" should be found via search in "apps/" dir
        resolver = AppResolver(project_root=str(temp_project))
        path, found = resolver.resolve_app("subapp")
        assert found is True
        assert "subapp" in path


# ---------------------------------------------------------------------------
# AppResolver caching
# ---------------------------------------------------------------------------


class TestCaching:
    def test_result_is_cached(self, temp_project):
        resolver = AppResolver(project_root=str(temp_project))
        result1 = resolver.resolve_app("myapp")
        result2 = resolver.resolve_app("myapp")
        assert result1 == result2
        assert "myapp" in resolver.app_cache

    def test_not_found_is_cached(self, temp_project):
        resolver = AppResolver(project_root=str(temp_project))
        resolver.resolve_app("totally_missing")
        assert "totally_missing" in resolver.app_cache


# ---------------------------------------------------------------------------
# AppResolver.resolve_all_apps
# ---------------------------------------------------------------------------


class TestResolveAllApps:
    def test_resolve_all_finds_valid_apps(self, temp_project):
        resolver = AppResolver(project_root=str(temp_project))
        result = resolver.resolve_all_apps(["myapp", "routesapp"])
        found = result["found"]
        assert "myapp" in found
        assert "routesapp" in found

    def test_resolve_all_reports_not_found(self, temp_project):
        resolver = AppResolver(project_root=str(temp_project))
        result = resolver.resolve_all_apps(["myapp", "missing_app"])
        not_found = result["not_found"]
        assert "missing_app" in not_found

    def test_resolve_all_skips_openviper_builtin(self, temp_project):
        resolver = AppResolver(project_root=str(temp_project))
        result = resolver.resolve_all_apps(["openviper.auth", "myapp"])
        found = result["found"]
        assert "openviper.auth" not in found

    def test_resolve_all_include_builtin(self, temp_project):
        resolver = AppResolver(project_root=str(temp_project))
        result = resolver.resolve_all_apps(["openviper.auth"], include_builtin=True)
        # openviper.auth probably not found in temp project, but it shouldn't be skipped
        # The key thing is it's not skipped — it will appear in not_found
        all_keys = list(result.get("found", {}).keys()) + list(result.get("not_found", []))
        assert "openviper.auth" in all_keys


# ---------------------------------------------------------------------------
# AppResolver.get_migrations_dir
# ---------------------------------------------------------------------------


class TestGetMigrationsDir:
    def test_returns_migrations_dir(self, temp_project):
        resolver = AppResolver(project_root=str(temp_project))
        migrations = resolver.get_migrations_dir("myapp")
        assert migrations is not None
        assert os.path.isdir(migrations)

    def test_creates_migrations_dir_if_missing(self, temp_project):
        resolver = AppResolver(project_root=str(temp_project))
        mdir = resolver.get_migrations_dir("myapp")
        assert mdir is not None
        assert os.path.exists(mdir)

    def test_creates_init_file(self, temp_project):
        # Remove existing migrations dir if it exists
        resolver = AppResolver(project_root=str(temp_project))
        mdir = resolver.get_migrations_dir("myapp")
        init = os.path.join(mdir, "__init__.py")
        assert os.path.exists(init)

    def test_not_found_app_returns_none(self, temp_project):
        resolver = AppResolver(project_root=str(temp_project))
        result = resolver.get_migrations_dir("nonexistent_xyz")
        assert result is None


# ---------------------------------------------------------------------------
# AppResolver.print_app_locations
# ---------------------------------------------------------------------------


class TestPrintAppLocations:
    def test_does_not_raise(self, temp_project, capsys):
        resolver = AppResolver(project_root=str(temp_project))
        resolver.print_app_locations(["myapp", "missing_app"])
        out = capsys.readouterr().out
        assert len(out) > 0

    def test_shows_found_app(self, temp_project, capsys):
        resolver = AppResolver(project_root=str(temp_project))
        resolver.print_app_locations(["myapp"])
        out = capsys.readouterr().out
        assert "myapp" in out

    def test_shows_not_found(self, temp_project, capsys):
        resolver = AppResolver(project_root=str(temp_project))
        resolver.print_app_locations(["missing_xyz"])
        out = capsys.readouterr().out
        assert "missing_xyz" in out


# ---------------------------------------------------------------------------
# AppResolver.print_app_not_found_error
# ---------------------------------------------------------------------------


class TestPrintNotFoundError:
    def test_does_not_raise(self, capsys):
        AppResolver.print_app_not_found_error("blog", ["/apps/blog", "/src/blog"])
        out = capsys.readouterr().out
        assert "blog" in out

    def test_includes_search_paths(self, capsys):
        AppResolver.print_app_not_found_error("myapp", ["/some/path"])
        out = capsys.readouterr().out
        assert "/some/path" in out


# ---------------------------------------------------------------------------
# AppResolver.print_app_not_in_settings_error
# ---------------------------------------------------------------------------


class TestPrintNotInSettingsError:
    def test_does_not_raise(self, capsys):
        AppResolver.print_app_not_in_settings_error("blog", "/project/blog")
        out = capsys.readouterr().out
        assert "blog" in out


# ---------------------------------------------------------------------------
# AppResolver._try_search_patterns
# ---------------------------------------------------------------------------


class TestSearchPatterns:
    def test_finds_nested_app(self, tmp_path):
        """App located in a nested dir should be found via walking."""
        nested = tmp_path / "level1" / "level2" / "deepapp"
        nested.mkdir(parents=True)
        (nested / "__init__.py").touch()
        (nested / "models.py").touch()

        resolver = AppResolver(project_root=str(tmp_path))
        path, found = resolver.resolve_app("deepapp")
        assert found is True
        assert "deepapp" in path
