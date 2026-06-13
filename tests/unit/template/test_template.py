"""Unit tests for openviper.template.plugin_loader."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from openviper.template import plugin_loader
from openviper.template.environment import get_jinja2_env


def mock_env() -> MagicMock:
    env = MagicMock()
    env.filters = {}
    env.globals = {}
    return env


class TestLoadDisabled:
    def setup_method(self):
        plugin_loader.reset()

    def test_disabled_plugin_sets_loaded(self):
        env = mock_env()
        with patch("openviper.template.plugin_loader.settings") as s:
            s.JINJA_PLUGINS = {"enable": 0}
            s.INSTALLED_APPS = []
            plugin_loader.load(env)
        assert plugin_loader.STATE.loaded is True

    def test_disabled_plugin_does_not_populate_env(self):
        env = mock_env()
        with patch("openviper.template.plugin_loader.settings") as s:
            s.JINJA_PLUGINS = {"enable": 0}
            s.INSTALLED_APPS = []
            plugin_loader.load(env)
        assert not env.filters
        assert not env.globals

    def test_missing_jinja_plugins_setting_disables(self):
        env = mock_env()
        with patch("openviper.template.plugin_loader.settings") as s:
            del s.JINJA_PLUGINS
            s.INSTALLED_APPS = []
            plugin_loader.load(env)
        assert plugin_loader.STATE.loaded is True


class TestLoadFastPath:
    def setup_method(self):
        plugin_loader.reset()

    def test_fast_path_applies_cached_filters(self):
        plugin_loader.STATE.loaded = True
        plugin_loader.STATE.filters["my_filter"] = lambda x: x
        env = mock_env()
        plugin_loader.load(env)
        assert "my_filter" in env.filters

    def test_fast_path_applies_cached_globals(self):
        plugin_loader.STATE.loaded = True
        plugin_loader.STATE.globals["my_global"] = lambda: 42
        env = mock_env()
        plugin_loader.load(env)
        assert "my_global" in env.globals

    def test_fast_path_copies_filters_not_aliases(self):
        """Mutating one env's filters must not affect the shared cache."""
        plugin_loader.STATE.loaded = True
        plugin_loader.STATE.filters["f"] = lambda x: x
        env1 = mock_env()
        plugin_loader.load(env1)
        env1.filters["injected"] = lambda x: x  # mutate env1's copy
        env2 = mock_env()
        plugin_loader.load(env2)
        assert "injected" not in plugin_loader.STATE.filters
        assert "injected" not in env2.filters

    def test_fast_path_copies_globals_not_aliases(self):
        plugin_loader.STATE.loaded = True
        plugin_loader.STATE.globals["g"] = lambda: None
        env1 = mock_env()
        plugin_loader.load(env1)
        env1.globals["injected"] = lambda: None
        env2 = mock_env()
        plugin_loader.load(env2)
        assert "injected" not in plugin_loader.STATE.globals
        assert "injected" not in env2.globals


class TestReset:
    def test_reset_clears_loaded(self):
        plugin_loader.STATE.loaded = True
        plugin_loader.reset()
        assert plugin_loader.STATE.loaded is False

    def test_reset_clears_filters(self):
        plugin_loader.STATE.filters["x"] = lambda v: v
        plugin_loader.reset()
        assert not plugin_loader.STATE.filters

    def test_reset_clears_globals(self):
        plugin_loader.STATE.globals["x"] = lambda: None
        plugin_loader.reset()
        assert not plugin_loader.STATE.globals

    def test_reset_clears_future(self):
        plugin_loader.STATE.future = MagicMock()
        plugin_loader.reset()
        assert plugin_loader.STATE.future is None

    def test_state_instances_have_independent_collections(self):
        """Each State instance must own its own mutable collections."""
        state_a = plugin_loader.State()
        state_b = plugin_loader.State()
        state_a.filters["unique_to_a"] = lambda v: v
        assert "unique_to_a" not in state_b.filters


class TestScanDirectory:
    def test_nonexistent_directory_returns_empty(self, tmp_path):
        result = plugin_loader.scan_directory(str(tmp_path / "no_such_dir"))
        assert not result

    def test_empty_directory_returns_empty(self, tmp_path):
        result = plugin_loader.scan_directory(str(tmp_path))
        assert not result

    def test_discovers_callable(self, tmp_path):
        (tmp_path / "greet.py").write_text("def greet(v):\n    return f'hi {v}'\n")
        result = plugin_loader.scan_directory(str(tmp_path))
        assert "greet" in result
        assert result["greet"]("world") == "hi world"

    def test_skips_private_names(self, tmp_path):
        (tmp_path / "private.py").write_text("def _hidden(v):\n    return v\n")
        result = plugin_loader.scan_directory(str(tmp_path))
        assert "_hidden" not in result

    def test_skips_dunder_files(self, tmp_path):
        (tmp_path / "__init__.py").write_text("def init_fn():\n    pass\n")
        result = plugin_loader.scan_directory(str(tmp_path))
        assert "init_fn" not in result

    def test_skips_non_py_files(self, tmp_path):
        (tmp_path / "readme.txt").write_text("hello")
        result = plugin_loader.scan_directory(str(tmp_path))
        assert not result

    def test_skips_symlinks_to_directories(self, tmp_path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (tmp_path / "link").symlink_to(subdir)
        result = plugin_loader.scan_directory(str(tmp_path))
        assert not result

    # Callable denylist tests
    def test_denylist_blocks_eval(self, tmp_path):
        (tmp_path / "danger.py").write_text("eval = eval\n")
        result = plugin_loader.scan_directory(str(tmp_path))
        assert "eval" not in result

    def test_denylist_blocks_exec(self, tmp_path):
        (tmp_path / "danger.py").write_text("exec = exec\n")
        result = plugin_loader.scan_directory(str(tmp_path))
        assert "exec" not in result

    def test_denylist_blocks_open(self, tmp_path):
        (tmp_path / "danger.py").write_text("open = open\n")
        result = plugin_loader.scan_directory(str(tmp_path))
        assert "open" not in result

    def test_denylist_blocks_compile(self, tmp_path):
        (tmp_path / "danger.py").write_text("compile = compile\n")
        result = plugin_loader.scan_directory(str(tmp_path))
        assert "compile" not in result

    def test_denylist_blocks_breakpoint(self, tmp_path):
        (tmp_path / "danger.py").write_text("breakpoint = breakpoint\n")
        result = plugin_loader.scan_directory(str(tmp_path))
        assert "breakpoint" not in result

    def test_safe_callable_alongside_denied_one(self, tmp_path):
        (tmp_path / "mixed.py").write_text("eval = eval\n\ndef safe(v):\n    return v\n")
        result = plugin_loader.scan_directory(str(tmp_path))
        assert "safe" in result
        assert "eval" not in result

    def test_symlink_to_file_is_rejected(self, tmp_path):
        """Symlinks to files must be skipped to prevent loading arbitrary code."""
        real_file = tmp_path / "real.py"
        real_file.write_text("def real_fn(v):\n    return v\n")
        link = tmp_path / "link.py"
        link.symlink_to(real_file)
        result = plugin_loader.scan_directory(str(tmp_path))
        assert "real_fn" in result
        assert len(result) == 1

    def test_denylist_blocks_getattr(self, tmp_path):
        (tmp_path / "danger.py").write_text("getattr = getattr\n")
        result = plugin_loader.scan_directory(str(tmp_path))
        assert "getattr" not in result

    def test_denylist_blocks_type(self, tmp_path):
        (tmp_path / "danger.py").write_text("type = type\n")
        result = plugin_loader.scan_directory(str(tmp_path))
        assert "type" not in result

    def test_import_failure_skips_module(self, tmp_path):
        (tmp_path / "broken.py").write_text("raise RuntimeError('boom')\n")
        result = plugin_loader.scan_directory(str(tmp_path))
        assert not result


class TestDiscoverPluginsPathGuard:
    def setup_method(self):
        plugin_loader.reset()

    def test_absolute_path_outside_project_is_allowed(self, tmp_path, caplog):
        # Absolute paths set by the operator are trusted; only relative traversal is blocked.
        cfg = {"path": "/etc"}
        with patch("openviper.template.plugin_loader.settings") as s:
            s.INSTALLED_APPS = []
            plugin_loader.discover_plugins(cfg)
        assert not any("escapes project root" in r.message for r in caplog.records)

    def test_path_traversal_string_is_rejected(self, tmp_path, caplog):
        cfg = {"path": "../../../etc"}
        with patch("openviper.template.plugin_loader.settings") as s:
            s.INSTALLED_APPS = []
            plugin_loader.discover_plugins(cfg)
        assert any("escapes project root" in r.message for r in caplog.records)

    def test_valid_relative_path_is_accepted(self, tmp_path, caplog):
        cfg = {"path": "jinja_plugins"}
        with patch("openviper.template.plugin_loader.settings") as s:
            s.INSTALLED_APPS = []
            plugin_loader.discover_plugins(cfg)
        assert not any("escapes project root" in r.message for r in caplog.records)


class TestPluginIntegration:
    def setup_method(self):
        plugin_loader.reset()
        get_jinja2_env.cache_clear()

    def teardown_method(self):
        plugin_loader.reset()
        get_jinja2_env.cache_clear()

    def test_filter_registered_via_app_plugin(self, tmp_path):
        filters_dir = tmp_path / "jinja_plugins" / "filters"
        filters_dir.mkdir(parents=True)
        (filters_dir / "shout.py").write_text("def shout(v):\n    return str(v).upper()\n")

        plugin_loader.reset()
        with patch("openviper.template.plugin_loader.settings") as s:
            s.JINJA_PLUGINS = {"enable": 1, "path": str(tmp_path / "jinja_plugins")}
            s.INSTALLED_APPS = []
            env = mock_env()
            plugin_loader.load(env)

        assert "shout" in env.filters
        assert env.filters["shout"]("hello") == "HELLO"

    def test_global_registered_via_app_plugin(self, tmp_path):
        globals_dir = tmp_path / "jinja_plugins" / "globals"
        globals_dir.mkdir(parents=True)
        (globals_dir / "answer.py").write_text("def answer():\n    return 42\n")

        plugin_loader.reset()
        with patch("openviper.template.plugin_loader.settings") as s:
            s.JINJA_PLUGINS = {"enable": 1, "path": str(tmp_path / "jinja_plugins")}
            s.INSTALLED_APPS = []
            env = mock_env()
            plugin_loader.load(env)

        assert "answer" in env.globals
        assert env.globals["answer"]() == 42


class TestApplyToEnv:
    def setup_method(self):
        plugin_loader.reset()

    def test_apply_to_env_copies_filters(self):
        plugin_loader.STATE.filters["upper"] = lambda x: x.upper()
        env = mock_env()
        plugin_loader.apply_to_env(env)
        assert "upper" in env.filters
        assert env.filters["upper"]("hi") == "HI"

    def test_apply_to_env_copies_globals(self):
        plugin_loader.STATE.globals["site_name"] = lambda: "openviper"
        env = mock_env()
        plugin_loader.apply_to_env(env)
        assert "site_name" in env.globals
        assert env.globals["site_name"]() == "openviper"

    def test_apply_to_env_skips_when_empty(self):
        env = mock_env()
        plugin_loader.apply_to_env(env)
        assert not env.filters
        assert not env.globals

    def test_apply_to_env_does_not_mutate_state(self):
        plugin_loader.STATE.filters["f"] = lambda x: x
        env = mock_env()
        plugin_loader.apply_to_env(env)
        env.filters["injected"] = lambda x: x
        assert "injected" not in plugin_loader.STATE.filters


class TestScanPluginDirs:
    def test_returns_both_filters_and_globals(self, tmp_path):
        filters_dir = tmp_path / "filters"
        globals_dir = tmp_path / "globals"
        filters_dir.mkdir()
        globals_dir.mkdir()
        (filters_dir / "upper.py").write_text("def upper(v):\n    return str(v).upper()\n")
        (globals_dir / "site.py").write_text("def site_name():\n    return 'openviper'\n")
        result = plugin_loader.scan_plugin_dirs(str(tmp_path))
        assert "upper" in result["filters"]
        assert "site_name" in result["globals"]

    def test_nonexistent_root_returns_empty_dicts(self, tmp_path):
        result = plugin_loader.scan_plugin_dirs(str(tmp_path / "no_such_dir"))
        assert not result["filters"]
        assert not result["globals"]

    def test_missing_subdirs_return_empty(self, tmp_path):
        (tmp_path / "filters").mkdir()
        result = plugin_loader.scan_plugin_dirs(str(tmp_path))
        assert not result["globals"]


class TestMergeScanned:
    def test_merges_filters_and_globals(self, tmp_path):
        filters_dir = tmp_path / "filters"
        globals_dir = tmp_path / "globals"
        filters_dir.mkdir()
        globals_dir.mkdir()
        (filters_dir / "upper.py").write_text("def upper(v):\n    return str(v).upper()\n")
        (globals_dir / "site.py").write_text("def site_name():\n    return 'openviper'\n")
        merged_filters: dict[str, object] = {}
        merged_globals: dict[str, object] = {}
        plugin_loader.merge_scanned(str(tmp_path), merged_filters, merged_globals)
        assert "upper" in merged_filters
        assert "site_name" in merged_globals

    def test_merge_preserves_existing_entries(self, tmp_path):
        filters_dir = tmp_path / "filters"
        filters_dir.mkdir()
        (filters_dir / "lower.py").write_text("def lower(v):\n    return str(v).lower()\n")
        merged_filters: dict[str, object] = {"existing": lambda x: x}
        merged_globals: dict[str, object] = {}
        plugin_loader.merge_scanned(str(tmp_path), merged_filters, merged_globals)
        assert "existing" in merged_filters
        assert "lower" in merged_filters

    def test_merge_with_empty_dir(self, tmp_path):
        merged_filters: dict[str, object] = {}
        merged_globals: dict[str, object] = {}
        plugin_loader.merge_scanned(str(tmp_path / "no_such_dir"), merged_filters, merged_globals)
        assert not merged_filters
        assert not merged_globals


class TestLogRegistered:
    def test_logs_filters_when_present(self, caplog):
        plugin_loader.STATE.filters["f"] = lambda x: x
        with caplog.at_level("DEBUG", logger="openviper.template.plugin_loader"):
            plugin_loader.log_registered("filter", plugin_loader.STATE.filters)
        assert any("filter" in r.message for r in caplog.records)

    def test_logs_globals_when_present(self, caplog):
        plugin_loader.STATE.globals["g"] = lambda: None
        with caplog.at_level("DEBUG", logger="openviper.template.plugin_loader"):
            plugin_loader.log_registered("global", plugin_loader.STATE.globals)
        assert any("global" in r.message for r in caplog.records)

    def test_skips_logging_when_empty(self, caplog):
        with caplog.at_level("DEBUG", logger="openviper.template.plugin_loader"):
            plugin_loader.log_registered("filter", {})
        assert not any("Registered" in r.message for r in caplog.records)
