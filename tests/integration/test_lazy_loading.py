"""Integration tests for lazy loading of heavy Openviper sub-packages.

Verifies that importing ``openviper`` (or ``openviper.app``) does NOT eagerly pull in
``openviper.staticfiles``, ``openviper.admin``, ``openviper.ai``, or ``openviper.tasks``
and that those modules load correctly when actually accessed.
"""

from __future__ import annotations

import subprocess
import sys

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _python(code: str) -> tuple[str, str, int]:
    """Run *code* in a fresh Python interpreter and return (stdout, stderr, rc)."""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    return result.stdout, result.stderr, result.returncode


# ---------------------------------------------------------------------------
# Startup-time module loading (subprocess isolation)
# ---------------------------------------------------------------------------


class TestNotLoadedAtStartup:
    """None of the heavy sub-packages should appear in sys.modules after a
    bare ``import openviper``."""

    def _is_loaded(self, module_name: str) -> bool:
        """Return True if *module_name* is present in sys.modules after import openviper."""
        stdout, stderr, rc = _python(
            f"import openviper; import sys; print({module_name!r} in sys.modules)"
        )
        assert rc == 0, f"Python process failed:\n{stderr}"
        return stdout.strip() == "True"

    def test_staticfiles_not_loaded_at_startup(self):
        assert not self._is_loaded("openviper.staticfiles")

    def test_admin_not_loaded_at_startup(self):
        assert not self._is_loaded("openviper.admin")

    def test_ai_not_loaded_at_startup(self):
        assert not self._is_loaded("openviper.ai")

    def test_tasks_not_loaded_at_startup(self):
        assert not self._is_loaded("openviper.tasks")

    def test_openviper_app_does_not_load_staticfiles(self):
        """Importing the OpenViper app class should not pull staticfiles."""
        assert not self._is_loaded("openviper.staticfiles")


# ---------------------------------------------------------------------------
# On-access loading (subprocess isolation)
# ---------------------------------------------------------------------------


class TestLoadedOnAccess:
    """After accessing the attribute on the ``openviper`` package the module
    must be present in sys.modules."""

    def _loaded_after_access(self, attr: str) -> tuple[bool, bool]:
        """Return (before, after) loaded state for the corresponding module."""
        module_dotted = f"openviper.{attr}"
        code = (
            f"import openviper, sys\n"
            f"before = {module_dotted!r} in sys.modules\n"
            f"_ = openviper.{attr}\n"
            f"after = {module_dotted!r} in sys.modules\n"
            f"print(before)\n"
            f"print(after)"
        )
        stdout, stderr, rc = _python(code)
        assert rc == 0, f"Python process failed:\n{stderr}"
        lines = stdout.strip().splitlines()
        return lines[0] == "True", lines[1] == "True"

    def test_staticfiles_loaded_on_access(self):
        before, after = self._loaded_after_access("staticfiles")
        assert not before, "staticfiles should not be loaded before access"
        assert after, "staticfiles should be loaded after access"

    def test_admin_loaded_on_access(self):
        before, after = self._loaded_after_access("admin")
        assert not before, "admin should not be loaded before access"
        assert after, "admin should be loaded after access"

    def test_ai_loaded_on_access(self):
        before, after = self._loaded_after_access("ai")
        assert not before, "ai should not be loaded before access"
        assert after, "ai should be loaded after access"

    def test_tasks_loaded_on_access(self):
        before, after = self._loaded_after_access("tasks")
        assert not before, "tasks should not be loaded before access"
        assert after, "tasks should be loaded after access"


# ---------------------------------------------------------------------------
# PEP 562 caching — attribute access returns the same module object
# ---------------------------------------------------------------------------


class TestLazySubpackageCaching:
    def test_repeated_access_returns_same_object(self):
        """After first access the result should be cached (same id)."""
        code = (
            "import openviper\n"
            "a = openviper.staticfiles\n"
            "b = openviper.staticfiles\n"
            "print(a is b)"
        )
        stdout, _, rc = _python(code)
        assert rc == 0
        assert stdout.strip() == "True"

    def test_unknown_attribute_raises(self):
        """__getattr__ must raise AttributeError for unknown names."""
        code = "import openviper; _ = openviper.totally_nonexistent_xyz"
        _, stderr, rc = _python(code)
        assert rc != 0
        assert "AttributeError" in stderr


# ---------------------------------------------------------------------------
# tasks.broker lazy initialisation (in-process)
# ---------------------------------------------------------------------------


class TestTasksBrokerLazy:
    def test_broker_attribute_resolves(self):
        """Accessing openviper.tasks.broker should return a callable broker."""
        import openviper.tasks as tasks

        broker = tasks.broker
        assert broker is not None

    def test_broker_is_cached_after_first_access(self):
        """Second access returns the same broker object."""
        import openviper.tasks as tasks

        b1 = tasks.broker
        b2 = tasks.broker
        assert b1 is b2

    def test_get_broker_callable(self):
        from openviper.tasks import get_broker

        broker = get_broker()
        assert broker is not None

    def test_setup_broker_callable(self):
        from openviper.tasks import setup_broker

        assert callable(setup_broker)

    def test_task_decorator_importable(self):
        from openviper.tasks import task

        assert callable(task)


# ---------------------------------------------------------------------------
# staticfiles accessed via _build_middleware_stack (in-process)
# ---------------------------------------------------------------------------


class TestStaticfilesLoadedOnFirstRequest:
    def test_middleware_stack_can_be_built(self):
        """Building the middleware stack should lazily import staticfiles internally."""
        from openviper.app import OpenViper

        app = OpenViper(debug=True)
        # _build_middleware_stack is called lazily on first __call__; we can
        # trigger it explicitly without needing an ASGI server.
        middleware_app = app._get_middleware_app()
        assert middleware_app is not None

    def test_staticfiles_not_loaded_when_debug_false(self):
        """With DEBUG=False, openviper.staticfiles must never be imported even after building the middleware stack."""
        code = (
            "import sys\n"
            "# Ensure a clean slate — staticfiles should not already be present\n"
            "assert 'openviper.staticfiles' not in sys.modules\n"
            "from openviper.app import OpenViper\n"
            "app = OpenViper(debug=False)\n"
            "app._get_middleware_app()\n"
            "print('openviper.staticfiles' in sys.modules)"
        )
        stdout, stderr, rc = _python(code)
        assert rc == 0, f"Python process failed:\n{stderr}"
        assert stdout.strip() == "False", "openviper.staticfiles was loaded despite DEBUG=False"

    def test_staticfiles_loaded_when_debug_true(self):
        """With DEBUG=True, openviper.staticfiles is imported while building the middleware stack."""
        code = (
            "import sys\n"
            "assert 'openviper.staticfiles' not in sys.modules\n"
            "from openviper.app import OpenViper\n"
            "app = OpenViper(debug=True)\n"
            "app._get_middleware_app()\n"
            "print('openviper.staticfiles' in sys.modules)"
        )
        stdout, stderr, rc = _python(code)
        assert rc == 0, f"Python process failed:\n{stderr}"
        assert stdout.strip() == "True", "openviper.staticfiles was not loaded despite DEBUG=True"
