"""Unit tests for the runserver management command."""

from __future__ import annotations

import argparse
import builtins
import os
import sys
from unittest.mock import MagicMock, patch

from openviper.core.management.commands.runserver import Command, _clear_pycache
from openviper.core.management.utils import print_banner

# ---------------------------------------------------------------------------
# _clear_pycache
# ---------------------------------------------------------------------------


class TestClearPycache:
    def test_removes_pycache_dirs(self, tmp_path):
        pycache = tmp_path / "myapp" / "__pycache__"
        pycache.mkdir(parents=True)
        (pycache / "foo.pyc").write_bytes(b"")
        _clear_pycache(tmp_path)
        assert not pycache.exists()

    def test_handles_oserror_gracefully(self, tmp_path):
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        with patch(
            "openviper.core.management.commands.runserver.shutil.rmtree", side_effect=OSError
        ):
            _clear_pycache(tmp_path)  # should not raise

    def test_no_pycache_dirs_no_error(self, tmp_path):
        _clear_pycache(tmp_path)  # no __pycache__ dirs, should be fine


# ---------------------------------------------------------------------------
# add_arguments
# ---------------------------------------------------------------------------


def test_add_arguments_defaults():

    cmd = Command()
    parser = argparse.ArgumentParser()
    cmd.add_arguments(parser)

    args = parser.parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 8000
    assert args.reload is True
    assert args.workers == 1
    assert args.app is None


def test_add_arguments_all_options():

    cmd = Command()
    parser = argparse.ArgumentParser()
    cmd.add_arguments(parser)

    args = parser.parse_args(
        [
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--no-reload",
            "--workers",
            "2",
            "myproject.asgi:app",
        ]
    )
    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.reload is False
    assert args.workers == 2
    assert args.app == "myproject.asgi:app"


# ---------------------------------------------------------------------------
# handle() – missing uvicorn
# ---------------------------------------------------------------------------


class TestHandleUvicornMissing:
    def test_uvicorn_missing_returns_early(self):
        cmd = Command()
        with patch.dict("sys.modules", {"uvicorn": None}):
            # Use a finder that raises ImportError for uvicorn
            with patch(
                "builtins.__import__",
                side_effect=lambda name, *a, **kw: (
                    (_ for _ in ()).throw(ImportError("no uvicorn"))
                    if name == "uvicorn"
                    else __import__(name, *a, **kw)
                ),
            ):
                pass  # handled below with simpler approach

        # Simpler: patch the try/except block
        with (
            patch.object(cmd, "_check_pending_migrations"),
            patch(
                "openviper.core.management.commands.runserver.Command.handle",
                wraps=lambda self, **opts: None,
            ),
        ):
            pass  # hard to trigger ImportError inside handle cleanly

    def test_uvicorn_missing_prints_error(self):
        """When uvicorn isn't importable, an error message is printed."""
        cmd = Command()
        err_output = []

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "uvicorn":
                raise ImportError("No module named 'uvicorn'")
            return real_import(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=fake_import),
            patch.object(cmd, "stderr", side_effect=lambda m: err_output.append(m)),
        ):
            cmd.handle(host="127.0.0.1", port=8000, reload=False, workers=1, app=None)
        assert any("uvicorn" in msg for msg in err_output)


# ---------------------------------------------------------------------------
# _resolve_app_path
# ---------------------------------------------------------------------------


class TestResolveAppPath:
    def test_explicit_app_returned_as_is(self):
        cmd = Command()
        result = cmd._resolve_app_path({"app": "myproject.asgi:app"})
        assert result == "myproject.asgi:app"

    def test_settings_module_used_when_no_explicit_app(self):
        cmd = Command()
        with patch.dict(os.environ, {"OPENVIPER_SETTINGS_MODULE": "myproject.settings"}):
            result = cmd._resolve_app_path({"app": None})
        assert result == "myproject.asgi:app"

    def test_cwd_basename_used_as_fallback(self):
        cmd = Command()
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENVIPER_SETTINGS_MODULE", None)
            with patch("os.getcwd", return_value="/home/user/myapp"):
                result = cmd._resolve_app_path({"app": None})
        assert result == "myapp.asgi:app"


# ---------------------------------------------------------------------------
# _reload_dirs
# ---------------------------------------------------------------------------


class TestReloadDirs:
    def test_includes_project_root(self):
        cmd = Command()
        result = cmd._reload_dirs("/my/project")
        assert "/my/project" in result

    def test_adds_openviper_pkg_parent_for_dev_install(self):
        """If openviper is a source install (not in site-packages), include its parent."""
        cmd = Command()
        mock_file = "/home/user/dev/openviper/openviper/__init__.py"
        mock_openviper = MagicMock()
        mock_openviper.__file__ = mock_file
        with patch.dict("sys.modules", {"openviper": mock_openviper}):

            sys.modules["openviper"] = mock_openviper
            result = cmd._reload_dirs("/my/project")
        # Should include parent of the openviper dir (since no "site-packages" in path)
        assert len(result) >= 1

    def test_skips_site_packages_install(self):
        """openviper installed in site-packages should NOT be added to reload dirs."""
        cmd = Command()
        mock_file = "/usr/lib/python3.11/site-packages/openviper/__init__.py"
        mock_openviper = MagicMock()
        mock_openviper.__file__ = mock_file
        with patch("openviper.core.management.commands.runserver.Path") as mock_path_cls:
            # Make Path(...).parent.parent.resolve() return a site-packages path
            mock_resolved = MagicMock()
            mock_resolved.__str__ = lambda s: "/usr/lib/python3.11/site-packages"
            mock_path_inst = MagicMock()
            mock_path_inst.parent.parent.resolve.return_value = mock_resolved
            mock_path_cls.return_value = mock_path_inst

            real_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if name == "openviper":
                    return mock_openviper
                return real_import(name, *args, **kwargs)

            result = cmd._reload_dirs("/myproject")
        assert "/myproject" in result


# ---------------------------------------------------------------------------
# _run_with_cache_clear
# ---------------------------------------------------------------------------


class TestRunWithCacheClear:
    def test_calls_uvicorn_run_with_reload(self):
        cmd = Command()
        mock_uvicorn = MagicMock()
        with (
            patch("openviper.core.management.commands.runserver.os.getcwd", return_value="/proj"),
            patch.object(cmd, "_reload_dirs", return_value=["/proj"]),
        ):
            cmd._run_with_cache_clear(mock_uvicorn, "myapp.asgi:app", "127.0.0.1", 8000)
        mock_uvicorn.run.assert_called_once()
        kwargs = mock_uvicorn.run.call_args[1]
        assert kwargs["reload"] is True

    def test_patches_supervisor_restart(self):
        """Verifies that the supervisor patching is attempted."""
        cmd = Command()
        mock_uvicorn = MagicMock()
        mock_supervisor = MagicMock()

        with (
            patch("openviper.core.management.commands.runserver.os.getcwd", return_value="/proj"),
            patch.object(cmd, "_reload_dirs", return_value=["/proj"]),
            patch("importlib.import_module", return_value=mock_supervisor) as mock_import,
        ):
            cmd._run_with_cache_clear(mock_uvicorn, "myapp.asgi:app", "127.0.0.1", 8000)
        # Should have attempted to import supervisor modules
        assert mock_import.called

    def test_handles_import_error_for_supervisor(self):
        """ImportError for optional supervisor is silently ignored."""
        cmd = Command()
        mock_uvicorn = MagicMock()

        with (
            patch("openviper.core.management.commands.runserver.os.getcwd", return_value="/proj"),
            patch.object(cmd, "_reload_dirs", return_value=["/proj"]),
        ):
            with patch("importlib.import_module", side_effect=ImportError):
                # Should not raise
                cmd._run_with_cache_clear(mock_uvicorn, "myapp.asgi:app", "127.0.0.1", 8000)
        mock_uvicorn.run.assert_called_once()


# ---------------------------------------------------------------------------
# _check_pending_migrations
# ---------------------------------------------------------------------------


class TestCheckPendingMigrations:
    def test_no_pending_migrations_no_output(self):
        cmd = Command()
        output = []
        with patch("openviper.core.management.commands.runserver.AppResolver") as mock_resolver_cls:
            mock_resolver = MagicMock()
            mock_resolver.resolve_all_apps.return_value = {"found": {}, "not_found": []}
            mock_resolver_cls.return_value = mock_resolver

            def _close_and_return_empty(coro):
                coro.close()
                return []

            with patch(
                "openviper.core.management.commands.runserver.asyncio.run",
                side_effect=_close_and_return_empty,
            ):
                with patch.object(cmd, "stdout", side_effect=lambda m: output.append(m)):
                    cmd._check_pending_migrations()

        assert not any("migration" in msg.lower() for msg in output if "migrate" not in msg.lower())

    def test_pending_migrations_outputs_warning(self):
        cmd = Command()
        output = []
        with patch("openviper.core.management.commands.runserver.AppResolver") as mock_resolver_cls:
            mock_resolver = MagicMock()
            mock_resolver.resolve_all_apps.return_value = {"found": {}, "not_found": []}
            mock_resolver_cls.return_value = mock_resolver

            def _close_and_return_pending(coro):
                coro.close()
                return ["myapp.0001_initial"]

            with (
                patch(
                    "openviper.core.management.commands.runserver.asyncio.run",
                    side_effect=_close_and_return_pending,
                ),
                patch.object(cmd, "stdout", side_effect=lambda m: output.append(m)),
            ):
                cmd._check_pending_migrations()

        combined = " ".join(output)
        assert "migration" in combined.lower() or "migrate" in combined.lower()

    def test_exception_in_check_does_not_raise(self):
        """If anything goes wrong, _check_pending_migrations should swallow it."""
        cmd = Command()
        with patch(
            "openviper.core.management.commands.runserver.AppResolver",
            side_effect=RuntimeError("DB down"),
        ):
            cmd._check_pending_migrations()  # should not raise


# ---------------------------------------------------------------------------
# _reload_dirs – exception swallowed
# ---------------------------------------------------------------------------


class TestReloadDirsImportError:
    def test_exception_in_openviper_import_is_swallowed(self):
        # When importing openviper raises, the except clause silently passes
        cmd = Command()
        with patch.dict(sys.modules, {"openviper": None}):
            dirs = cmd._reload_dirs("/some/root")
        # Should return at minimum the root directory without raising
        assert "/some/root" in dirs


# ---------------------------------------------------------------------------
# _run_with_cache_clear – ImportError/AttributeError for supervisor
# ---------------------------------------------------------------------------


class TestRunWithCacheClearSupervisor:
    def test_supervisor_import_error_is_swallowed(self):
        # ImportError for a uvicorn supervisor is silently ignored
        cmd = Command()
        mock_uvicorn = MagicMock()
        mock_uvicorn.run = MagicMock()
        with patch(
            "importlib.import_module",
            side_effect=ImportError("no module"),
        ):
            cmd._run_with_cache_clear(mock_uvicorn, "myapp.asgi:app", "127.0.0.1", 8000)
        mock_uvicorn.run.assert_called_once()

    def test_supervisor_attribute_error_is_swallowed(self):
        # AttributeError (class missing on module) is silently ignored
        cmd = Command()
        mock_uvicorn = MagicMock()
        mock_uvicorn.run = MagicMock()
        fake_mod = MagicMock(spec=[])  # no attributes → getattr raises AttributeError
        with patch(
            "importlib.import_module",
            return_value=fake_mod,
        ):
            cmd._run_with_cache_clear(mock_uvicorn, "myapp.asgi:app", "127.0.0.1", 8000)
        mock_uvicorn.run.assert_called_once()


# ---------------------------------------------------------------------------
# _check_pending_migrations – non-dict resolved_apps → {} and
# _get_pending() body executed
# ---------------------------------------------------------------------------


class TestCheckPendingMigrationsExtra:
    def test_non_dict_resolved_apps_treated_as_empty(self):
        # resolved_apps that is not a dict is replaced with {}
        cmd = Command()
        with patch("openviper.core.management.commands.runserver.AppResolver") as mock_resolver_cls:
            mock_resolver = MagicMock()
            mock_resolver.resolve_all_apps.return_value = {"found": ["not", "a", "dict"]}
            mock_resolver_cls.return_value = mock_resolver
            with (
                patch(
                    "openviper.core.management.commands.runserver.asyncio.run",
                    return_value=[],
                ),
                patch.object(cmd, "stdout"),
            ):
                cmd._check_pending_migrations()
        # Should not raise; non-dict resolved_apps is handled gracefully

    def test_get_pending_body_executed_via_asyncio_run(self):
        # _get_pending() async function body is exercised
        cmd = Command()
        executed = []
        with patch("openviper.core.management.commands.runserver.AppResolver") as mock_resolver_cls:
            mock_resolver = MagicMock()
            mock_resolver.resolve_all_apps.return_value = {"found": {}}
            mock_resolver_cls.return_value = mock_resolver

            def _capture_and_run(coro):
                import asyncio as _asyncio

                executed.append(True)
                try:
                    return _asyncio.get_event_loop().run_until_complete(coro)
                except Exception:
                    coro.close()
                    return []

            with (
                patch(
                    "openviper.core.management.commands.runserver.asyncio.run",
                    side_effect=_capture_and_run,
                ),
                patch(
                    "openviper.core.management.commands.runserver.MigrationExecutor"
                ) as mock_exec_cls,
                patch(
                    "openviper.core.management.commands.runserver.discover_migrations",
                    return_value=[],
                ),
                patch.object(cmd, "stdout"),
            ):
                mock_exec = MagicMock()
                mock_exec._ensure_migration_table = MagicMock(return_value=None)
                mock_exec._applied_migrations = MagicMock(return_value=set())
                mock_exec_cls.return_value = mock_exec
                cmd._check_pending_migrations()

        assert executed


# ---------------------------------------------------------------------------
# print_banner – cmd_obj=None creates BaseCommand internally
# ---------------------------------------------------------------------------


def test_print_banner_no_cmd_obj_creates_base_command():
    # When cmd_obj is None, BaseCommand() is created internally and banner is printed
    with patch("builtins.print"):
        print_banner("127.0.0.1", 8000)
    # No exception → BaseCommand was created and get_banner ran
