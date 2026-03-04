import os
import tempfile
from pathlib import Path

import pytest

from openviper.core.app_resolver import AppResolver


@pytest.fixture
def mock_project():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # Valid direct app
        app1 = root / "app1"
        app1.mkdir()
        (app1 / "__init__.py").touch()
        (app1 / "models.py").touch()

        # Valid dot-converted app (nested.app2)
        nested = root / "nested" / "app2"
        nested.mkdir(parents=True)
        (nested / "__init__.py").touch()
        (nested / "routes.py").touch()

        # Valid relative app under 'src'
        src_app = root / "src" / "app3"
        src_app.mkdir(parents=True)
        (src_app / "__init__.py").touch()
        (src_app / "migrations").mkdir()

        # Valid search pattern app
        random_app = root / "deep" / "folder" / "app4"
        random_app.mkdir(parents=True)
        (random_app / "__init__.py").touch()
        (random_app / "models.py").touch()

        # Invalid app (missing models/routes/migrations)
        invalid = root / "invalid_app"
        invalid.mkdir()
        (invalid / "__init__.py").touch()

        # Cache exclusions (nodes_modules)
        node_modules = root / "node_modules" / "app5"
        node_modules.mkdir(parents=True)
        (node_modules / "__init__.py").touch()
        (node_modules / "models.py").touch()

        yield td


def test_resolver_initialization(mock_project):
    resolver = AppResolver(project_root=mock_project)
    assert resolver.project_root == mock_project


def test_get_project_root():
    resolver = AppResolver()
    assert resolver.project_root == os.getcwd()


def test_resolve_direct_path(mock_project):
    resolver = AppResolver(mock_project)
    path, found = resolver.resolve_app("app1")
    assert found
    assert path == os.path.join(mock_project, "app1")

    # Test caching
    path2, found2 = resolver.resolve_app("app1")
    assert found2
    assert path2 == path

    # Dot-converted direct path
    path_dot, found_dot = resolver.resolve_app("nested.app2")
    assert found_dot
    assert path_dot == os.path.join(mock_project, "nested/app2")


def test_resolve_relative_path(mock_project):
    resolver = AppResolver(mock_project)
    path, found = resolver.resolve_app(
        "apps.app3"
    )  # 'app3' is under 'src', searching fallback dirs
    assert found
    assert path == os.path.join(mock_project, "src/app3")


def test_resolve_search_patterns(mock_project):
    resolver = AppResolver(mock_project)
    path, found = resolver.resolve_app("some.prefix.app4")  # 'app4' is deep
    assert found
    assert path == os.path.join(mock_project, "deep/folder/app4")


def test_resolve_not_found_and_invalid(mock_project):
    resolver = AppResolver(mock_project)
    # Excluded directory should not be found
    path, found = resolver.resolve_app("app5")
    assert not found
    assert path is None

    # True invalid app
    path2, found2 = resolver.resolve_app("invalid_app")
    assert not found2


def test_resolve_all_apps(mock_project):
    resolver = AppResolver(mock_project)
    installed = ["app1", "nested.app2", "missing", "openviper.admin"]
    result = resolver.resolve_all_apps(installed)

    assert "app1" in result["found"]
    assert "nested.app2" in result["found"]
    assert "missing" in result["not_found"]
    # openviper. prefixed apps are ignored
    assert "openviper.admin" not in result["found"]
    assert "openviper.admin" not in result["not_found"]


def test_get_migrations_dir(mock_project):
    resolver = AppResolver(mock_project)

    # App3 already has migrations dir empty
    mig_dir = resolver.get_migrations_dir("apps.app3")
    assert mig_dir is not None
    assert os.path.exists(mig_dir)
    assert not os.path.exists(
        os.path.join(mig_dir, "__init__.py")
    )  # Should not touch existing dicts

    # App1 doesn't have migrations, it should be created
    mig_dir2 = resolver.get_migrations_dir("app1")
    assert mig_dir2 is not None
    assert os.path.exists(os.path.join(mock_project, "app1/migrations/__init__.py"))

    # Not found app
    mig_dir3 = resolver.get_migrations_dir("missing")
    assert mig_dir3 is None


def test_print_functions(mock_project, capsys):
    resolver = AppResolver(mock_project)

    resolver.print_app_locations(["app1", "missing"])
    captured = capsys.readouterr()
    assert "app1:" in captured.out
    assert "missing" in captured.out
    assert "Not Found:" in captured.out

    resolver.print_app_not_found_error("missing", ["/path1", "/path2"])
    captured_err = capsys.readouterr()
    assert "ERROR: App 'missing' not found" in captured_err.out
    assert "/path1" in captured_err.out

    resolver.print_app_not_in_settings_error("newapp", "/found/path")
    captured_unmapped = capsys.readouterr()
    assert "App 'newapp' exists but not in INSTALLED_APPS" in captured_unmapped.out
    assert "/found/path" in captured_unmapped.out
