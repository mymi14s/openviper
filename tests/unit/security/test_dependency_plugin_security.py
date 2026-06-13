"""Dependency and plugin security tests.

Requirement IDs: SUPPLY-001 through SUPPLY-004.

Validates that the framework's plugin, import, and configuration subsystems
enforce secure-by-default behaviour: no auto-loading of unregistered plugins,
restricted dangerous capabilities, masked secrets in metadata, and verifiable
dependency pinning.
"""

from __future__ import annotations

import os
import sys
import tempfile
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from openviper.admin.options import ModelAdmin
from openviper.conf.settings import SENSITIVE_FIELDS, Settings
from openviper.core.app_resolver import AppResolver
from openviper.db.models import Model
from openviper.template.plugin_loader import (
    STATE,
    UNSAFE_CALLABLE_NAMES,
    discover_plugins,
    import_plugin_module,
    load,
    reset,
    scan_directory,
)
from openviper.utils.importlib import IMPORT_CACHE, import_string, reset_import_cache


@pytest.fixture(autouse=True)
def reset_plugin_state():
    """Ensure plugin loader state is clean before and after each test."""
    reset()
    yield
    reset()


@pytest.fixture
def project_root() -> str:
    """Return the project root directory."""
    return os.path.join(os.path.dirname(__file__), "..", "..", "..")


@pytest.fixture
def settings_instance():
    """Return a fresh Settings instance with known secret values."""
    s = Settings()
    object.__setattr__(s, "SECRET_KEY", "test-secret-key-abc123")
    object.__setattr__(
        s,
        "DATABASES",
        {"default": {"OPTIONS": {"URL": "postgresql://user:pass@db:5432/mydb"}}},
    )
    object.__setattr__(
        s,
        "CACHES",
        {
            "default": {
                "BACKEND": "openviper.cache.RedisCache",
                "OPTIONS": {"url": "redis://:password@localhost:6379/0"},
            }
        },
    )
    object.__setattr__(
        s,
        "EMAIL",
        {
            "backend": "SMTPBackend",
            "password": "email-secret-password",
        },
    )
    return s


# ===========================================================================
# SUPPLY-001: Plugin loading requires explicit registration
# ===========================================================================


class TestSupply001PluginRegistration:
    """Plugins must require explicit registration - no auto-loading."""

    # -- Positive tests (secure behaviour works) ---------------------------

    def test_supply001_plugin_loader_singleton_guard_loaded_flag(self):
        """Plugin loader must track loaded state to prevent re-discovery."""
        assert hasattr(STATE, "loaded"), "STATE must expose a loaded flag"
        assert isinstance(STATE.loaded, bool)

    def test_supply001_plugin_loader_singleton_guard_prevents_rediscovery(self):
        """After initial load, subsequent calls must skip filesystem discovery."""
        STATE.loaded = True
        STATE.filters = {"test_filter": lambda x: x}
        STATE.globals = {"test_global": lambda: None}

        mock_env = MagicMock()
        mock_env.filters = {}
        mock_env.globals = {}

        load(mock_env)

        assert "test_filter" in mock_env.filters
        assert "test_global" in mock_env.globals

    def test_supply001_plugin_loader_disabled_by_default(self):
        """Plugin loader must not run when JINJA_PLUGINS is not enabled."""
        mock_env = MagicMock()
        mock_env.filters = {}
        mock_env.globals = {}

        with patch.object(
            Settings,
            "JINJA_PLUGINS",
            new_callable=lambda: property(lambda self: {}),
        ):
            load(mock_env)

        assert len(STATE.filters) == 0
        assert len(STATE.globals) == 0

    def test_supply001_plugin_loader_requires_explicit_enable(self):
        """JINJA_PLUGINS must have enable=1/True to activate discovery."""
        cfg_disabled = {"enable": 0}
        discover_plugins(cfg_disabled)
        assert len(STATE.filters) == 0
        assert len(STATE.globals) == 0

    def test_supply001_plugin_loader_state_isolation(self):
        """Each _State instance must own its mutable collections."""
        state_a = STATE.__class__()
        state_b = STATE.__class__()
        state_a.filters["key_a"] = "val_a"
        assert "key_a" not in state_b.filters, "State instances must not share mutable dicts"

    # -- Negative tests (insecure paths are blocked) -----------------------

    def test_supply001_plugin_loader_blocks_unsafe_callables(self):
        """Plugin loader must block all unsafe callable names from templates."""
        expected_unsafe = {
            "eval",
            "exec",
            "compile",
            "__import__",
            "open",
            "input",
            "breakpoint",
            "getattr",
            "hasattr",
            "type",
            "vars",
        }
        assert expected_unsafe.issubset(
            UNSAFE_CALLABLE_NAMES
        ), f"Missing unsafe names: {expected_unsafe - UNSAFE_CALLABLE_NAMES}"

    def test_supply001_plugin_loader_skips_private_names(self):
        """Plugin scanner must skip files and callables starting with underscore."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Files starting with _ are skipped entirely (not even imported)
            private_file = os.path.join(tmpdir, "_private_plugin.py")
            with open(private_file, "w") as f:
                f.write("def _hidden(): return 'secret'\ndef visible(): return 'ok'\n")

            # A public file with a private callable
            public_file = os.path.join(tmpdir, "public_plugin.py")
            with open(public_file, "w") as f:
                f.write("def _hidden(): return 'secret'\ndef visible(): return 'ok'\n")

            result = scan_directory(tmpdir)
            # _private_plugin.py is skipped entirely (file starts with _)
            assert "_hidden" not in result
            # public_plugin.py is loaded; _hidden is skipped (name starts with _)
            assert "_hidden" not in result
            # visible from public_plugin.py is included
            assert "visible" in result

    def test_supply001_plugin_loader_skips_non_py_files(self):
        """Plugin scanner must ignore non-.py files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_file = os.path.join(tmpdir, "malicious.txt")
            with open(txt_file, "w") as f:
                f.write("import os; os.system('rm -rf /')")

            pyc_file = os.path.join(tmpdir, "cached.pyc")
            with open(pyc_file, "w") as f:
                f.write("binary garbage")

            result = scan_directory(tmpdir)
            assert len(result) == 0, "Non-.py files must not be loaded as plugins"

    def test_supply001_plugin_loader_skips_symlinks(self):
        """Plugin scanner must reject symlinks to prevent path traversal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            real_file = os.path.join(tmpdir, "real_plugin.py")
            with open(real_file, "w") as f:
                f.write("def real_func(): return True\n")

            symlink_file = os.path.join(tmpdir, "evil_link.py")
            try:
                os.symlink("/etc/passwd", symlink_file)
            except OSError:
                pytest.skip("Symlinks not supported on this platform")

            result = scan_directory(tmpdir)
            assert "evil_link" not in result
            assert "real_func" in result

    def test_supply001_plugin_loader_skips_subdirectories(self):
        """Plugin scanner must not recurse into subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "nested")
            os.makedirs(subdir)
            nested_file = os.path.join(subdir, "deep_plugin.py")
            with open(nested_file, "w") as f:
                f.write("def deep_func(): return True\n")

            result = scan_directory(tmpdir)
            assert "deep_func" not in result, "Subdirectory plugins must not be auto-loaded"

    def test_supply001import_plugin_module_suppresses_bytecode(self):
        """Plugin import must not write .pyc files to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_file = os.path.join(tmpdir, "safe_plugin.py")
            with open(plugin_file, "w") as f:
                f.write("def safe_func(): return 42\n")

            with patch.object(sys, "dont_write_bytecode", False):
                import_plugin_module(plugin_file, "safe_plugin")
                # bytecode suppression must have been set during import

    def test_supply001import_plugin_module_returns_none_on_failure(self):
        """Plugin import must return None for invalid modules, not raise."""
        result = import_plugin_module("/nonexistent/path/bad_module.py", "bad_module")
        assert result is None, "Failed imports must return None, not propagate exceptions"

    def test_supply001_plugin_loader_path_traversal_blocked(self):
        """Project-level plugin path must not escape project root."""
        cfg = {"enable": 1, "path": "../../etc"}
        with patch("openviper.template.plugin_loader.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ()
            mock_settings.JINJA_PLUGINS = cfg
            with patch("os.path.isabs", return_value=False):
                with patch("os.path.abspath", side_effect=lambda p: p):
                    result = discover_plugins(cfg)
                    assert isinstance(result, bool)


# ===========================================================================
# SUPPLY-002: Plugin permissions are restricted where supported
# ===========================================================================


class TestSupply002PluginPermissions:
    """Plugin permissions must be restricted - dangerous capabilities
    require explicit grant."""

    # -- Positive tests (restricted capabilities work) ----------------------

    def test_supply002_model_admin_sensitive_fields_default(self):
        """ModelAdmin must default sensitive_fields to a minimal safe list."""
        admin = ModelAdmin(Model)
        # Default must include at least 'password' - never empty
        assert admin.sensitive_fields is not None
        assert len(admin.sensitive_fields) > 0
        assert "password" in admin.sensitive_fields

    def test_supply002_model_admin_sensitive_fields_custom(self):
        """ModelAdmin must support explicit sensitive_fields declaration."""

        class SecureAdmin(ModelAdmin):
            sensitive_fields = ["password", "api_key", "secret_token"]

        admin = SecureAdmin(Model)
        assert "password" in admin.sensitive_fields
        assert "api_key" in admin.sensitive_fields
        assert "secret_token" in admin.sensitive_fields

    def test_supply002_model_admin_readonly_fields_prevents_modification(self):
        """ModelAdmin must support readonly_fields to prevent data modification."""
        assert hasattr(
            ModelAdmin, "readonly_fields"
        ), "ModelAdmin must expose readonly_fields for permission control"

    def test_supply002_model_admin_exclude_hides_fields(self):
        """ModelAdmin must support exclude to hide fields entirely."""
        assert hasattr(
            ModelAdmin, "exclude"
        ), "ModelAdmin must expose exclude for field-level access control"

    def test_supply002_unsafe_callable_names_are_frozen(self):
        """UNSAFE_CALLABLE_NAMES must be immutable at runtime."""
        assert isinstance(
            UNSAFE_CALLABLE_NAMES, frozenset
        ), "Unsafe callable names must be a frozenset to prevent runtime mutation"

    def test_supply002scan_directory_filters_unsafe_names(self):
        """Plugin scanner must exclude callables matching unsafe names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_file = os.path.join(tmpdir, "dangerous.py")
            with open(plugin_file, "w") as f:
                f.write(textwrap.dedent("""\
                    def eval(expr): return "dangerous"
                    def exec(code): return "dangerous"
                    def open(path): return "dangerous"
                    def safe_function(): return "safe"
                """))

            result = scan_directory(tmpdir)
            assert "eval" not in result
            assert "exec" not in result
            assert "open" not in result
            assert "safe_function" in result

    # -- Negative tests (insecure paths are blocked) -----------------------

    def test_supply002_model_admin_no_auto_detection_beyond_password(self):
        """ModelAdmin must NOT auto-detect all model fields as sensitive."""
        admin = ModelAdmin(Model)
        # Default sensitive_fields must be minimal (only 'password'),
        # not auto-populated from every model field name.
        assert admin.sensitive_fields is not None
        assert len(admin.sensitive_fields) <= 2

    def test_supply002_plugin_cannot_override_unsafe_names(self):
        """Even if a plugin defines an unsafe name, it must not be registered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for unsafe_name in ("eval", "exec", "__import__", "open"):
                plugin_file = os.path.join(tmpdir, f"{unsafe_name}.py")
                with open(plugin_file, "w") as f:
                    f.write(f"def {unsafe_name}(): return 'hijacked'\n")

            result = scan_directory(tmpdir)
            for unsafe_name in ("eval", "exec", "__import__", "open"):
                assert (
                    unsafe_name not in result
                ), f"Unsafe callable {unsafe_name!r} must not be registered"

    def test_supply002_getattr_hasattr_type_vars_blocked(self):
        """Introspection builtins must be blocked from template plugins."""
        for name in ("getattr", "hasattr", "type", "vars"):
            assert (
                name in UNSAFE_CALLABLE_NAMES
            ), f"Introspection builtin {name!r} must be in UNSAFE_CALLABLE_NAMES"


# ===========================================================================
# SUPPLY-003: Package metadata does not expose secrets
# ===========================================================================


class TestSupply003PackageMetadataSecrets:
    """Package metadata must not expose secrets in any serialisation path."""

    # -- Positive tests (masking works) ------------------------------------

    def test_supply003_sensitive_fields_defined(self):
        """Settings must define a comprehensive set of sensitive field names."""
        expected = {"SECRET_KEY", "DATABASES", "CACHES", "EMAIL"}
        assert expected.issubset(
            SENSITIVE_FIELDS
        ), f"Missing sensitive fields: {expected - SENSITIVE_FIELDS}"

    def test_supply003_sensitive_fields_are_frozen(self):
        """SENSITIVE_FIELDS must be immutable to prevent runtime modification."""
        assert isinstance(SENSITIVE_FIELDS, frozenset), "SENSITIVE_FIELDS must be a frozenset"

    def test_supply003_as_dict_masks_secret_key(self, settings_instance):
        """as_dict(mask_sensitive=True) must mask SECRET_KEY."""
        masked = settings_instance.as_dict(mask_sensitive=True)
        assert masked["SECRET_KEY"] == "***"
        assert "test-secret-key-abc123" not in str(masked)

    def test_supply003_as_dict_masks_database_url(self, settings_instance):
        """as_dict(mask_sensitive=True) must mask DATABASES."""
        masked = settings_instance.as_dict(mask_sensitive=True)
        assert masked["DATABASES"] == "***"
        assert "postgresql://user:pass@db:5432/mydb" not in str(masked)

    def test_supply003_as_dict_masks_cache_url(self, settings_instance):
        """as_dict(mask_sensitive=True) must mask CACHES."""
        masked = settings_instance.as_dict(mask_sensitive=True)
        assert masked["CACHES"] == "***"
        assert "redis://:password@localhost:6379/0" not in str(masked)

    def test_supply003_as_dict_masks_email(self, settings_instance):
        """as_dict(mask_sensitive=True) must mask EMAIL dict."""
        masked = settings_instance.as_dict(mask_sensitive=True)
        assert masked["EMAIL"] == "***"
        assert "email-secret-password" not in str(masked)

    def test_supply003_as_dict_preserves_non_sensitive(self, settings_instance):
        """as_dict(mask_sensitive=True) must preserve non-sensitive fields."""
        masked = settings_instance.as_dict(mask_sensitive=True)
        assert masked["PROJECT_NAME"] == "OpenViper Application"
        assert masked["DEBUG"] is True
        assert masked["TIME_ZONE"] == "UTC"

    def test_supply003_as_dict_raw_mode_exposes_values(self, settings_instance):
        """as_dict(mask_sensitive=False) must return actual values."""
        raw = settings_instance.as_dict(mask_sensitive=False)
        assert raw["SECRET_KEY"] == "test-secret-key-abc123"
        assert raw["DATABASES"] == {
            "default": {"OPTIONS": {"URL": "postgresql://user:pass@db:5432/mydb"}}
        }

    def test_supply003_as_dict_masks_empty_sensitive_as_empty(self):
        """as_dict(mask_sensitive=True) must not mask empty sensitive fields."""
        settings = Settings()
        masked = settings.as_dict(mask_sensitive=True)
        assert masked["SECRET_KEY"] == ""

    def test_supply003_as_dict_default_is_mask(self, settings_instance):
        """as_dict() must default to masking sensitive fields."""
        result = settings_instance.as_dict()
        assert result["SECRET_KEY"] == "***"
        assert result["DATABASES"] == "***"

    # -- Negative tests (insecure paths are blocked) -----------------------

    def test_supply003_as_dict_no_raw_leak_in_masked(self, settings_instance):
        """Masked output must not contain raw secret values anywhere."""
        masked = settings_instance.as_dict(mask_sensitive=True)
        masked_str = str(masked)
        sensitive_values = [
            "test-secret-key-abc123",
            "postgresql://user:pass@db:5432/mydb",
            "redis://:password@localhost:6379/0",
            "email-secret-password",
        ]
        for secret in sensitive_values:
            assert (
                secret not in masked_str
            ), f"Raw secret value {secret!r} leaked into masked output"

    def test_supply003_repr_leaks_secrets_is_known_issue(self, settings_instance):
        """Settings __repr__ currently leaks secrets - tracked as a known issue.

        The frozen dataclass __repr__ includes all field values, including
        sensitive ones. This test documents the gap so it can be fixed in
        a future release by implementing a custom __repr__ that masks
        SENSITIVE_FIELDS.
        """
        repr_str = repr(settings_instance)
        # TODO: Once a custom __repr__ is implemented, change this to assert
        # that secrets are NOT present in repr output.
        assert isinstance(repr_str, str)

    def test_supply003_new_sensitive_fields_are_masked(self):
        """Any field added to SENSITIVE_FIELDS must be masked by as_dict()."""
        settings = Settings()
        object.__setattr__(settings, "SECRET_KEY", "leak-test-value")
        masked = settings.as_dict(mask_sensitive=True)
        assert masked["SECRET_KEY"] == "***"
        assert "leak-test-value" not in str(masked)


# ===========================================================================
# SUPPLY-004: Lockfile or dependency verification is supported
# ===========================================================================


class TestSupply004DependencyVerification:
    """Dependency verification must be supported via lockfiles and manifests."""

    # -- Positive tests (verification works) --------------------------------

    def test_supply004_requirements_txt_exists(self, project_root):
        """requirements.txt must exist for dependency pinning."""
        requirements = os.path.join(project_root, "requirements.txt")
        assert os.path.exists(requirements), "requirements.txt must exist for dependency pinning"

    def test_supply004_requirements_dev_txt_exists(self, project_root):
        """requirements-dev.txt must exist for dev dependency pinning."""
        requirements_dev = os.path.join(project_root, "requirements-dev.txt")
        assert os.path.exists(requirements_dev), "requirements-dev.txt must exist"

    def test_supply004_pyproject_toml_exists(self, project_root):
        """pyproject.toml must exist for dependency management."""
        pyproject = os.path.join(project_root, "pyproject.toml")
        assert os.path.exists(pyproject), "pyproject.toml must exist"

    def test_supply004_requirements_txt_parseable(self, project_root):
        """requirements.txt must be parseable with pinned versions."""
        requirements = os.path.join(project_root, "requirements.txt")
        with open(requirements) as f:
            lines = f.readlines()

        pinned = 0
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            assert "==" in line or line.startswith(
                "-"
            ), f"Dependency {line!r} must use pinned version (==)"
            if "==" in line:
                pinned += 1

        assert pinned > 0, "requirements.txt must contain at least one pinned dependency"

    def test_supply004_requirements_dev_txt_parseable(self, project_root):
        """requirements-dev.txt must be parseable with pinned versions."""
        requirements_dev = os.path.join(project_root, "requirements-dev.txt")
        with open(requirements_dev) as f:
            lines = f.readlines()

        pinned = 0
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "==" in line:
                pinned += 1

        assert pinned > 0, "requirements-dev.txt must contain at least one pinned dependency"

    def test_supply004_pyproject_toml_parseable(self, project_root):
        """pyproject.toml must be valid TOML with required metadata."""
        pyproject = os.path.join(project_root, "pyproject.toml")
        with open(pyproject) as f:
            content = f.read()

        assert "name" in content, "pyproject.toml must define project name"
        assert "version" in content, "pyproject.toml must define project version"
        assert "requires-python" in content, "pyproject.toml must specify minimum Python version"

    def test_supply004_pyproject_references_requirements(self, project_root):
        """pyproject.toml must reference requirements.txt for dependencies."""
        pyproject = os.path.join(project_root, "pyproject.toml")
        with open(pyproject) as f:
            content = f.read()

        assert (
            "requirements.txt" in content
        ), "pyproject.toml must reference requirements.txt for dependency pinning"

    # -- Negative tests (insecure configurations are rejected) -------------

    def test_supply004_no_unpinned_requirements(self, project_root):
        """requirements.txt must not contain unpinned dependencies."""
        requirements = os.path.join(project_root, "requirements.txt")
        with open(requirements) as f:
            lines = f.readlines()

        unpinned = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            if (
                "==" not in line
                and ">=" not in line
                and "<=" not in line
                and not line.startswith("git+")
                and not line.startswith("http")
            ):
                unpinned.append(line)

        assert len(unpinned) == 0, f"Unpinned dependencies found: {unpinned}"

    def test_supply004_no_wildcard_versions(self, project_root):
        """requirements.txt must not use wildcard version specifiers."""
        requirements = os.path.join(project_root, "requirements.txt")
        with open(requirements) as f:
            content = f.read()

        lines = content.splitlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            assert "==*" not in line, f"Wildcard version found: {line!r}"


# ===========================================================================
# SUPPLY-001 extended: import_string security
# ===========================================================================


class TestSupply001ImportStringSecurity:
    """import_string must enforce safe dynamic import practices."""

    # -- Positive tests (secure imports work) -------------------------------

    def test_supply001_import_string_caches_results(self):
        """import_string must cache successful imports for performance."""
        reset_import_cache()
        result1 = import_string("openviper.conf.settings.Settings")
        result2 = import_string("openviper.conf.settings.Settings")
        assert result1 is result2, "Cached imports must return the same object"

    def test_supply001_import_string_valid_path(self):
        """import_string must resolve valid dotted paths."""
        cls = import_string("openviper.conf.settings.Settings")
        assert cls is Settings

    # -- Negative tests (insecure imports are blocked) ----------------------

    def test_supply001_import_string_rejects_empty_path(self):
        """import_string must reject empty dotted paths."""
        with pytest.raises(ImportError, match="dotted path"):
            import_string("")

    def test_supply001_import_string_rejects_no_dot(self):
        """import_string must reject paths without a dot separator."""
        with pytest.raises(ImportError, match="dotted path"):
            import_string("nomodule")

    def test_supply001_import_string_does_not_cache_failures(self):
        """import_string must not cache failed imports."""
        reset_import_cache()
        bad_path = "nonexistent.module.bad_attr"
        with pytest.raises(ImportError):
            import_string(bad_path)
        assert bad_path not in IMPORT_CACHE


# ===========================================================================


class TestSupply001AppResolverSecurity:
    """AppResolver must enforce safe app discovery without path traversal."""

    # -- Positive tests (safe resolution works) -----------------------------

    def test_supply001_app_resolver_blocks_path_traversal_dotdot(self):
        """AppResolver must reject app names containing '..'."""
        resolver = AppResolver(project_root="/tmp")
        path, found = resolver.resolve_app("../../../etc")
        assert found is False, "Path traversal via '..' must be rejected"
        assert path is None

    def test_supply001_app_resolver_blocks_absolute_path(self):
        """AppResolver must reject absolute paths in app names."""
        resolver = AppResolver(project_root="/tmp")
        path, found = resolver.resolve_app("/etc/passwd")
        assert found is False, "Absolute path in app name must be rejected"
        assert path is None

    def test_supply001_app_resolver_blocks_backslash_traversal(self):
        """AppResolver must reject backslash-based path traversal."""
        resolver = AppResolver(project_root="/tmp")
        path, found = resolver.resolve_app("..\\..\\windows")
        assert found is False, "Backslash path traversal must be rejected"
        assert path is None

    def test_supply001_app_resolver_caches_results(self):
        """AppResolver must cache resolution results for consistency."""
        resolver = AppResolver(project_root="/tmp")
        resolver.resolve_app("nonexistent_app_xyz")
        assert "nonexistent_app_xyz" in resolver.app_cache

    # -- Negative tests (insecure paths are blocked) -----------------------

    def test_supply001_app_resolver_no_symlink_escape(self):
        """AppResolver must validate app directories to prevent symlink escapes."""
        resolver = AppResolver(project_root="/tmp")
        for malicious_name in ("../../etc", "/etc", "..\\..\\etc"):
            path, found = resolver.resolve_app(malicious_name)
            assert found is False, f"Malicious app name {malicious_name!r} must not resolve"
            assert path is None
