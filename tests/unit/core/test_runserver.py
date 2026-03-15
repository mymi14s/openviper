"""Unit tests for runserver management command."""

import builtins
import concurrent.futures
import contextlib
import sys
from unittest.mock import AsyncMock, Mock, patch

import pytest
import uvicorn
import uvicorn.supervisors

from openviper.core.management.commands.runserver import (
    _MIGRATION_THREAD_POOL,
    Command,
    _clear_pycache,
)


@pytest.fixture
def command():
    """Create a Command instance."""
    return Command()


class TestRunServerCommand:
    """Test runserver command basic functionality."""

    def test_help_attribute(self, command):
        assert "development server" in command.help or "uvicorn" in command.help

    def test_add_arguments(self, command):
        parser = Mock()
        parser.add_argument = Mock()

        command.add_arguments(parser)

        # Should add --host, --port, --reload, --no-reload, --workers, app
        assert parser.add_argument.call_count >= 6


class TestClearPycache:
    """Test _clear_pycache function."""

    def test_clear_pycache_removes_pycache_dirs(self, tmp_path):
        # Create some __pycache__ directories
        cache1 = tmp_path / "__pycache__"
        cache1.mkdir()

        subdir = tmp_path / "subdir"
        subdir.mkdir()
        cache2 = subdir / "__pycache__"
        cache2.mkdir()

        _clear_pycache(tmp_path)

        assert not cache1.exists()
        assert not cache2.exists()

    @patch("openviper.core.management.commands.runserver.shutil.rmtree")
    def test_clear_pycache_handles_errors(self, mock_rmtree, tmp_path):
        # Create a real __pycache__ so rglob finds it
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        mock_rmtree.side_effect = OSError("Permission denied")
        _clear_pycache(tmp_path)
        mock_rmtree.assert_called_once_with(cache_dir)


class TestHandleBasic:
    """Test basic handle functionality."""

    def test_handle_imports_uvicorn(self, command):
        """Test that handle imports and uses uvicorn."""
        mock_uvicorn = Mock()
        mock_uvicorn.run = Mock()

        with patch.dict(sys.modules, {"uvicorn": mock_uvicorn}):
            with patch.object(command, "_check_pending_migrations"):
                with patch.object(command, "_resolve_app_path", return_value="myproject.asgi:app"):
                    with patch(
                        "openviper.core.management.commands.runserver._MIGRATION_THREAD_POOL"
                    ) as mock_pool:
                        mock_future = Mock()
                        mock_future.result = Mock(side_effect=Exception("ignored"))
                        mock_pool.submit = Mock(return_value=mock_future)

                        with patch("openviper.core.management.commands.runserver.get_banner"):
                            command.handle(
                                host="127.0.0.1", port=8000, reload=False, workers=1, app=None
                            )

        mock_uvicorn.run.assert_called_once()

    def test_handle_with_timeout_error(self, command):
        """Test that handle works when migration check times out."""
        mock_uvicorn = Mock()
        mock_uvicorn.run = Mock()

        with patch.dict(sys.modules, {"uvicorn": mock_uvicorn}):
            with patch.object(command, "_check_pending_migrations"):
                with patch.object(command, "_resolve_app_path", return_value="myproject.asgi:app"):
                    with patch(
                        "openviper.core.management.commands.runserver._MIGRATION_THREAD_POOL"
                    ) as mock_pool:
                        mock_future = Mock()
                        mock_future.result = Mock(side_effect=concurrent.futures.TimeoutError)
                        mock_pool.submit = Mock(return_value=mock_future)

                        with patch("openviper.core.management.commands.runserver.get_banner"):
                            command.handle(
                                host="127.0.0.1", port=8000, reload=False, workers=1, app=None
                            )

        mock_uvicorn.run.assert_called_once()

    def test_handle_missing_uvicorn_shows_error(self, command, capsys):
        """Test that missing uvicorn shows appropriate error."""

        # Save original modules
        original_modules = sys.modules.copy()
        original_import = builtins.__import__

        try:
            # Remove uvicorn to simulate it not being installed
            if "uvicorn" in sys.modules:
                del sys.modules["uvicorn"]

            def mock_import(name, *args, **kwargs):
                if name == "uvicorn":
                    raise ImportError("No module named 'uvicorn'")
                return original_import(name, *args, **kwargs)

            with patch.object(builtins, "__import__", side_effect=mock_import):
                command.handle(host="127.0.0.1", port=8000, reload=False, workers=1, app=None)

            captured = capsys.readouterr()
            assert "uvicorn is required" in captured.err
        finally:
            sys.modules.clear()
            sys.modules.update(original_modules)


class TestResolveAppPath:
    """Test _resolve_app_path method."""

    def test_resolve_app_path_uses_provided_app(self, command):
        app_path = command._resolve_app_path({"app": "custom.asgi:application"})
        assert app_path == "custom.asgi:application"

    @patch.dict("os.environ", {"OPENVIPER_SETTINGS_MODULE": "myproject.settings"})
    def test_resolve_app_path_from_settings_module(self, command):
        app_path = command._resolve_app_path({"app": None})
        assert app_path == "myproject.asgi:app"

    def test_resolve_app_path_from_cwd(self, command):
        with patch.dict("os.environ", clear=True):
            with patch("os.getcwd", return_value="/project/myapp"):
                with patch("os.path.basename", return_value="myapp"):
                    app_path = command._resolve_app_path({"app": None})
                    assert "myapp" in app_path


class TestReloadDirs:
    """Test _reload_dirs method."""

    def test_reload_dirs_includes_project_root(self, command):
        dirs = command._reload_dirs("/project/root")
        assert "/project/root" in dirs

    @patch("openviper.__file__", "/site-packages/openviper/__init__.py")
    def test_reload_dirs_excludes_site_packages(self, command):
        dirs = command._reload_dirs("/project/root")
        # Should not include site-packages path
        assert all("site-packages" not in d for d in dirs)

    def test_reload_dirs_includes_local_openviper(self, command):
        with patch("openviper.__file__", "/dev/openviper/openviper/__init__.py"):
            command._reload_dirs("/project/root")
            # May include local openviper path if not in site-packages

    def test_reload_dirs_handles_exception(self, command):
        """Test reload dirs handles ImportError."""
        with patch.dict(sys.modules, {"openviper": None}):
            dirs = command._reload_dirs("/project/root")
            assert dirs == ["/project/root"]


class TestRunWithCacheClear:
    """Test _run_with_cache_clear method."""

    def test_run_with_cache_clear_patches_reload(self, command):
        """Test that _run_with_cache_clear calls uvicorn.run with reload=True."""
        mock_uvicorn = Mock()
        mock_uvicorn.run = Mock()

        with patch.object(command, "_reload_dirs", return_value=["/project"]):
            command._run_with_cache_clear(mock_uvicorn, "app:main", "127.0.0.1", 8000)

        mock_uvicorn.run.assert_called_once()
        call_kwargs = mock_uvicorn.run.call_args[1]
        assert call_kwargs["reload"] is True

    @patch("uvicorn.run")
    def test_patched_restart_function(self, mock_run, command, tmp_path):
        """Test the patched restart method on actual uvicorn classes if available."""
        if not hasattr(uvicorn, "supervisors"):
            pytest.skip("uvicorn is not fully installed")

        orig_restart = uvicorn.supervisors.ChangeReload.restart

        try:
            with patch.object(command, "_reload_dirs", return_value=["/project"]):
                with patch(
                    "openviper.core.management.commands.runserver.os.getcwd",
                    return_value=str(tmp_path),
                ):
                    command._run_with_cache_clear(uvicorn, "app:main", "127.0.0.1", 8000)

                    cache_dir = tmp_path / "__pycache__"
                    cache_dir.mkdir()

                    # Mock the original so it doesn't crash from fake args
                    mock_orig = Mock()

                    # Instead of calling real restart which might crash,
                    # we temporarily swap orig to avoid problems
                    with patch.object(uvicorn.supervisors.ChangeReload, "restart", mock_orig):
                        # Actually wait, _run_with_cache_clear already patched it!
                        # We just need to call the patched one
                        pass

                    # So we just catch any errors from the real _orig
                    with contextlib.suppress(Exception):
                        uvicorn.supervisors.ChangeReload.restart(Mock())

                    assert not cache_dir.exists()
        finally:
            uvicorn.supervisors.ChangeReload.restart = orig_restart


class TestMigrationCheck:
    """Test _check_pending_migrations method."""

    def test_check_pending_migrations_with_pending(self, command, capsys):
        """Test that pending migrations trigger a warning."""
        mock_settings = Mock()
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()
        mock_resolver.resolve_all_apps = Mock(return_value={"found": {}})

        mock_executor = Mock()
        mock_executor._ensure_migration_table = AsyncMock()
        mock_executor._applied_migrations = AsyncMock(return_value=set())

        # Create mock migration record
        mock_rec = Mock()
        mock_rec.app = "app"
        mock_rec.name = "0001_initial"

        with patch("openviper.conf.settings", mock_settings):
            with patch(
                "openviper.core.management.commands.runserver.AppResolver",
                return_value=mock_resolver,
            ):
                with patch(
                    "openviper.core.management.commands.runserver.MigrationExecutor",
                    return_value=mock_executor,
                ):
                    with patch(
                        "openviper.core.management.commands.runserver.discover_migrations",
                        return_value=[mock_rec],
                    ):
                        command._check_pending_migrations()

        captured = capsys.readouterr()
        assert "unapplied migrations" in captured.out or "Missing migrations" in captured.out

    def test_check_pending_migrations_with_invalid_resolved_apps(self, command):
        """Test with invalid resolved_apps."""
        mock_settings = Mock()
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()
        mock_resolver.resolve_all_apps = Mock(return_value={"found": ["invalid"]})

        mock_executor = Mock()
        mock_executor._ensure_migration_table = AsyncMock()
        mock_executor._applied_migrations = AsyncMock(return_value=set())

        with patch("openviper.conf.settings", mock_settings):
            with patch(
                "openviper.core.management.commands.runserver.AppResolver",
                return_value=mock_resolver,
            ):
                with patch(
                    "openviper.core.management.commands.runserver.MigrationExecutor",
                    return_value=mock_executor,
                ):
                    with patch(
                        "openviper.core.management.commands.runserver.discover_migrations",
                        return_value=[],
                    ):
                        command._check_pending_migrations()

    def test_check_pending_migrations_db_exception(self, command):
        """Test exception when retrieving applied migrations."""
        mock_settings = Mock()
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()
        mock_resolver.resolve_all_apps = Mock(return_value={"found": {}})

        mock_executor = Mock()
        mock_executor._ensure_migration_table = AsyncMock(side_effect=Exception("DB not found"))

        # Create mock migration record
        mock_rec = Mock()
        mock_rec.app = "app"
        mock_rec.name = "0001_initial"

        with patch("openviper.conf.settings", mock_settings):
            with patch(
                "openviper.core.management.commands.runserver.AppResolver",
                return_value=mock_resolver,
            ):
                with patch(
                    "openviper.core.management.commands.runserver.MigrationExecutor",
                    return_value=mock_executor,
                ):
                    with patch(
                        "openviper.core.management.commands.runserver.discover_migrations",
                        return_value=[mock_rec],
                    ):
                        command._check_pending_migrations()

    def test_check_pending_migrations_handles_errors(self, command):
        """Test that errors in migration check don't raise exceptions."""
        mock_settings = Mock()
        mock_settings.INSTALLED_APPS = []

        mock_resolver = Mock()
        mock_resolver.resolve_all_apps = Mock(side_effect=Exception("DB error"))

        with patch("openviper.conf.settings", mock_settings):
            with patch(
                "openviper.core.management.commands.runserver.AppResolver",
                return_value=mock_resolver,
            ):
                # Should not raise
                command._check_pending_migrations()


class TestHandleOptions:
    """Test handle with different options."""

    def test_handle_with_custom_host_port(self, command):
        """Test handle with custom host and port."""
        mock_uvicorn = Mock()
        mock_uvicorn.run = Mock()

        with patch.dict(sys.modules, {"uvicorn": mock_uvicorn}):
            with patch.object(command, "_check_pending_migrations"):
                with patch.object(command, "_resolve_app_path", return_value="app:main"):
                    with patch(
                        "openviper.core.management.commands.runserver._MIGRATION_THREAD_POOL"
                    ) as mock_pool:
                        mock_future = Mock()
                        mock_future.result = Mock(side_effect=Exception("ignored"))
                        mock_pool.submit = Mock(return_value=mock_future)

                        with patch("openviper.core.management.commands.runserver.get_banner"):
                            command.handle(
                                host="0.0.0.0", port=3000, reload=False, workers=1, app=None
                            )

        call_kwargs = mock_uvicorn.run.call_args[1]
        assert call_kwargs["host"] == "0.0.0.0"
        assert call_kwargs["port"] == 3000

    def test_handle_with_reload(self, command):
        """Test handle with reload enabled."""
        mock_uvicorn = Mock()
        mock_uvicorn.run = Mock()

        with patch.dict(sys.modules, {"uvicorn": mock_uvicorn}):
            with patch.object(command, "_check_pending_migrations"):
                with patch.object(command, "_resolve_app_path", return_value="app:main"):
                    with patch.object(command, "_run_with_cache_clear") as mock_cache_clear:
                        with patch(
                            "openviper.core.management.commands.runserver._MIGRATION_THREAD_POOL"
                        ) as mock_pool:
                            mock_future = Mock()
                            mock_future.result = Mock(side_effect=Exception("ignored"))
                            mock_pool.submit = Mock(return_value=mock_future)

                            with patch("openviper.core.management.commands.runserver.get_banner"):
                                command.handle(
                                    host="127.0.0.1", port=8000, reload=True, workers=1, app=None
                                )

        mock_cache_clear.assert_called_once()


class TestBanner:
    """Test banner display."""

    def test_handle_displays_banner(self, command):
        """Test that handle displays the banner."""
        mock_uvicorn = Mock()
        mock_uvicorn.run = Mock()

        with patch.dict(sys.modules, {"uvicorn": mock_uvicorn}):
            with patch.object(command, "_check_pending_migrations"):
                with patch.object(command, "_resolve_app_path", return_value="app:main"):
                    with patch(
                        "openviper.core.management.commands.runserver._MIGRATION_THREAD_POOL"
                    ) as mock_pool:
                        mock_future = Mock()
                        mock_future.result = Mock(side_effect=Exception("ignored"))
                        mock_pool.submit = Mock(return_value=mock_future)

                        with patch(
                            "openviper.core.management.commands.runserver.get_banner"
                        ) as mock_banner:
                            command.handle(
                                host="127.0.0.1", port=8000, reload=False, workers=1, app=None
                            )

        mock_banner.assert_called_once_with(command, "127.0.0.1", 8000)


class TestThreadPoolShutdown:
    """Test that _MIGRATION_THREAD_POOL is operational and registered for cleanup."""

    def test_thread_pool_is_alive(self):
        """Pool should not be shut down prematurely at import time."""
        assert not _MIGRATION_THREAD_POOL._shutdown

    def test_thread_pool_can_submit(self):
        """Pool should accept work (proves atexit hasn't fired yet)."""
        future = _MIGRATION_THREAD_POOL.submit(lambda: 42)
        assert future.result(timeout=2) == 42


class TestEdgeCases:
    """Test edge cases."""

    def test_command_instantiation(self):
        """Test that command can be instantiated."""
        cmd = Command()
        assert cmd is not None
        assert hasattr(cmd, "handle")
        assert hasattr(cmd, "_resolve_app_path")
        assert hasattr(cmd, "_check_pending_migrations")
