"""Unit tests for openviper.template.render_to_string."""

from unittest.mock import MagicMock, patch

import pytest

from openviper.template import render_to_string
from openviper.template.environment import get_jinja2_env


class TestRenderToString:
    def setup_method(self):
        get_jinja2_env.cache_clear()

    def teardown_method(self):
        get_jinja2_env.cache_clear()

    def test_basic_render(self, tmp_path):
        # Create a temporary template
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        template_file = template_dir / "hello.html"
        template_file.write_text("Hello {{ name }}!")

        with patch("openviper.template.environment.settings") as mock_settings:
            mock_settings.TEMPLATES_DIR = str(template_dir)
            mock_settings.INSTALLED_APPS = ()

            result = render_to_string("hello.html", {"name": "OpenViper"})
            assert result == "Hello OpenViper!"

    def test_render_no_context(self, tmp_path):
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        template_file = template_dir / "static.html"
        template_file.write_text("Static Content")

        with patch("openviper.template.environment.settings") as mock_settings:
            mock_settings.TEMPLATES_DIR = str(template_dir)
            mock_settings.INSTALLED_APPS = ()

            result = render_to_string("static.html")
            assert result == "Static Content"

    def test_discovery_from_apps(self, tmp_path):
        # 1. Project-level template
        proj_dir = tmp_path / "proj_templates"
        proj_dir.mkdir()
        (proj_dir / "base.html").write_text("Base")

        # 2. App-level template
        app_dir = tmp_path / "my_app"
        app_templates = app_dir / "templates"
        app_templates.mkdir(parents=True)
        (app_templates / "app.html").write_text("App")
        (app_dir / "__init__.py").touch()

        # Mock app module
        mock_app = MagicMock()
        mock_app.__file__ = str(app_dir / "__init__.py")

        with (
            patch("openviper.template.environment.settings") as mock_settings,
            patch("importlib.import_module", return_value=mock_app),
        ):
            mock_settings.TEMPLATES_DIR = str(proj_dir)
            mock_settings.INSTALLED_APPS = ("my_app",)

            # verify it finds both
            from openviper.template.environment import get_template_directories

            dirs = get_template_directories()
            assert len(dirs) == 2
            assert str(proj_dir) in dirs
            assert str(app_templates) in dirs

            # verify it can render from both
            assert render_to_string("base.html") == "Base"
            assert render_to_string("app.html") == "App"

    def test_template_not_found(self, tmp_path):
        with patch("openviper.template.environment.settings") as mock_settings:
            mock_settings.TEMPLATES_DIR = str(tmp_path)
            mock_settings.INSTALLED_APPS = ()

            from jinja2 import TemplateNotFound

            with pytest.raises(TemplateNotFound):
                render_to_string("missing.html")

    def test_render_lazy_string(self, tmp_path):
        from openviper.utils.translation import gettext_lazy as _

        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        (template_dir / "lazy.html").write_text("Message: {{ msg }}")

        with patch("openviper.template.environment.settings") as mock_settings:
            mock_settings.TEMPLATES_DIR = str(template_dir)
            mock_settings.INSTALLED_APPS = ()

            # Lazy strings should be evaluated during render
            lazy_msg = _("Hello World")
            result = render_to_string("lazy.html", {"msg": lazy_msg})
            assert result == "Message: Hello World"
