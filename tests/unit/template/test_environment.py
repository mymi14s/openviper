"""Unit tests for openviper.template.environment — Jinja2 environment factory."""

from __future__ import annotations

import pytest
from markupsafe import Markup

import openviper.template.environment as env_module
from openviper.template.environment import get_jinja2_env


class TestGetJinja2Env:
    def setup_method(self):
        get_jinja2_env.cache_clear()

    def teardown_method(self):
        get_jinja2_env.cache_clear()

    def test_returns_environment(self, tmp_path):
        env = get_jinja2_env((str(tmp_path),))
        assert env is not None
        assert env.loader is not None

    def test_caches_environment(self, tmp_path):
        paths = (str(tmp_path),)
        env1 = get_jinja2_env(paths)
        env2 = get_jinja2_env(paths)
        assert env1 is env2

    def test_different_paths_different_envs(self, tmp_path):
        dir1 = tmp_path / "a"
        dir2 = tmp_path / "b"
        dir1.mkdir()
        dir2.mkdir()
        env1 = get_jinja2_env((str(dir1),))
        env2 = get_jinja2_env((str(dir2),))
        assert env1 is not env2

    def test_cache_clear_allows_new_env(self, tmp_path):
        paths = (str(tmp_path),)
        env1 = get_jinja2_env(paths)
        get_jinja2_env.cache_clear()
        env2 = get_jinja2_env(paths)
        assert env2 is not env1

    def test_renders_template(self, tmp_path):
        (tmp_path / "test.html").write_text("Hello {{ name }}!")
        env = get_jinja2_env((str(tmp_path),))
        result = env.get_template("test.html").render(name="World")
        assert result == "Hello World!"

    def test_raises_import_error_when_jinja2_unavailable(self):
        original = env_module.Environment
        try:
            env_module.Environment = None
            get_jinja2_env.cache_clear()
            with pytest.raises(ImportError, match="jinja2"):
                get_jinja2_env(("/tmp/nonexistent_xyz",))
        finally:
            env_module.Environment = original
            get_jinja2_env.cache_clear()

    # ------------------------------------------------------------------
    # Autoescape (security fix)
    # ------------------------------------------------------------------

    def test_autoescape_escapes_html_in_html_template(self, tmp_path):
        (tmp_path / "page.html").write_text("<p>{{ content }}</p>")
        env = get_jinja2_env((str(tmp_path),))
        result = env.get_template("page.html").render(content="<script>alert(1)</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_autoescape_escapes_html_in_jinja2_template(self, tmp_path):
        (tmp_path / "page.jinja2").write_text("{{ xss }}")
        env = get_jinja2_env((str(tmp_path),))
        result = env.get_template("page.jinja2").render(xss='<b class="x">')
        assert "<b" not in result
        assert "&lt;b" in result

    def test_safe_markup_passes_through_unescaped(self, tmp_path):
        (tmp_path / "page.html").write_text("{{ content }}")
        env = get_jinja2_env((str(tmp_path),))
        result = env.get_template("page.html").render(content=Markup("<b>bold</b>"))
        assert result == "<b>bold</b>"

    def test_autoescape_active_for_html_extension(self, tmp_path):
        env = get_jinja2_env((str(tmp_path),))
        autoescape = env.autoescape
        assert (autoescape("page.html") if callable(autoescape) else autoescape) is True
