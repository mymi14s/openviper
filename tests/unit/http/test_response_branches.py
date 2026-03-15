"""Unit tests for missing branches in openviper.http.response."""

import datetime
import uuid
from unittest.mock import MagicMock, patch

import pytest

from openviper.http.response import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    _cache_clear,
    _compute_template_search_paths,
    _get_jinja2_env,
)


class TestImportErrorHandling:
    """Test import error handling for Jinja2."""

    def test_environment_is_none_when_jinja2_not_imported(self):
        """Should handle case where Jinja2 is not installed."""
        with patch("openviper.http.response.Environment", None):
            with pytest.raises(ImportError, match="jinja2 is required"):
                # Try to get environment when Environment is None
                _get_jinja2_env(("/tmp",))

    def test_get_jinja2_env_success_path(self):
        """Should return jinja2 environment when Environment is available."""
        mock_env = MagicMock()

        with patch("openviper.http.response.Environment", MagicMock()):
            with patch("openviper.http.response.get_jinja2_env", return_value=mock_env):
                result = _get_jinja2_env(("/tmp",))

                # Should return the environment
                assert result == mock_env


class TestComputeTemplateSearchPaths:
    """Test _compute_template_search_paths function."""

    def test_handles_import_error_for_app(self):
        """Should handle ImportError when importing app module."""
        base_dir = "/tmp/templates"
        installed_apps = ("nonexistent.app",)

        # Should not raise, just skip the app
        result = _compute_template_search_paths(base_dir, installed_apps)

        # Should only have base_dir
        assert result == (base_dir,)

    def test_handles_app_without_file_attribute(self):
        """Should handle app module without __file__ attribute."""
        base_dir = "/tmp/templates"
        mock_module = MagicMock()
        # Simulate module without __file__
        del mock_module.__file__

        with patch("openviper.http.response.importlib.import_module", return_value=mock_module):
            result = _compute_template_search_paths(base_dir, ("test.app",))

        # Should only have base_dir since app has no __file__
        assert result == (base_dir,)

    def test_handles_app_with_none_file(self):
        """Should handle app module with __file__ = None."""
        base_dir = "/tmp/templates"
        mock_module = MagicMock()
        mock_module.__file__ = None

        with patch("openviper.http.response.importlib.import_module", return_value=mock_module):
            result = _compute_template_search_paths(base_dir, ("test.app",))

        # Should only have base_dir
        assert result == (base_dir,)

    def test_handles_attribute_error_for_app(self):
        """Should handle AttributeError when accessing app attributes."""
        base_dir = "/tmp/templates"

        def side_effect(app_path):
            mock = MagicMock()
            # Make hasattr check fail with AttributeError
            type(mock).__file__ = property(
                lambda self: (_ for _ in ()).throw(AttributeError("No __file__"))
            )
            return mock

        with patch("openviper.http.response.importlib.import_module", side_effect=side_effect):
            result = _compute_template_search_paths(base_dir, ("test.app",))

        # Should only have base_dir
        assert result == (base_dir,)

    def test_skips_app_without_templates_dir(self, tmp_path):
        """Should skip app if templates directory doesn't exist."""
        base_dir = str(tmp_path / "templates")
        (tmp_path / "templates").mkdir()

        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        app_file = app_dir / "__init__.py"
        app_file.write_text("")

        mock_module = MagicMock()
        mock_module.__file__ = str(app_file)

        with patch("openviper.http.response.importlib.import_module", return_value=mock_module):
            result = _compute_template_search_paths(base_dir, ("test.app",))

        # Should only have base_dir since app has no templates dir
        assert result == (base_dir,)

    def test_includes_app_with_templates_dir(self, tmp_path):
        """Should include app templates directory when it exists."""
        base_dir = str(tmp_path / "templates")
        (tmp_path / "templates").mkdir()

        app_dir = tmp_path / "myapp"
        app_dir.mkdir()
        app_file = app_dir / "__init__.py"
        app_file.write_text("")
        (app_dir / "templates").mkdir()

        mock_module = MagicMock()
        mock_module.__file__ = str(app_file)

        with patch("openviper.http.response.importlib.import_module", return_value=mock_module):
            result = _compute_template_search_paths(base_dir, ("test.app",))

        # Should have both base_dir and app templates
        assert len(result) == 2
        assert result[0] == base_dir
        assert result[1] == str(app_dir / "templates")


class TestCacheClear:
    """Test _cache_clear function."""

    def test_cache_clear_clears_both_caches(self):
        """Should clear both get_jinja2_env and _compute_template_search_paths caches."""
        with patch("openviper.http.response.get_jinja2_env") as mock_get_env:
            with patch("openviper.http.response._compute_template_search_paths") as mock_compute:
                mock_get_env.cache_clear = MagicMock()
                mock_compute.cache_clear = MagicMock()

                _cache_clear()

                mock_get_env.cache_clear.assert_called_once()
                mock_compute.cache_clear.assert_called_once()


class TestJSONResponseDefaultEncoder:
    """Test JSONResponse._default_encoder branches."""

    def test_default_encoder_handles_datetime(self):
        """Should serialize datetime to ISO format when called directly."""
        dt = datetime.datetime(2025, 1, 15, 12, 0, 0)
        result = JSONResponse._default_encoder(dt)

        # Should return ISO format string
        assert result == "2025-01-15T12:00:00"

    def test_default_encoder_handles_date(self):
        """Should serialize date to ISO format when called directly."""
        d = datetime.date(2025, 1, 15)
        result = JSONResponse._default_encoder(d)

        # Should return ISO format string
        assert result == "2025-01-15"

    def test_default_encoder_handles_uuid(self):
        """Should serialize UUID to string when called directly."""
        test_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        result = JSONResponse._default_encoder(test_uuid)

        # Should return UUID string
        assert result == "12345678-1234-5678-1234-567812345678"

    def test_serializes_datetime(self):
        """Should serialize datetime to ISO format."""
        dt = datetime.datetime(2025, 1, 15, 12, 0, 0)
        response = JSONResponse({"timestamp": dt})

        # Should contain ISO format string
        assert b"2025-01-15T12:00:00" in response.body

    def test_serializes_date(self):
        """Should serialize date to ISO format."""
        d = datetime.date(2025, 1, 15)
        response = JSONResponse({"date": d})

        # Should contain ISO format string
        assert b"2025-01-15" in response.body

    def test_serializes_uuid(self):
        """Should serialize UUID to string."""
        test_uuid = uuid.uuid4()
        response = JSONResponse({"id": test_uuid})

        # Should contain UUID string
        assert str(test_uuid).encode() in response.body

    def test_raises_for_non_serializable(self):
        """Should raise TypeError for non-serializable objects."""

        class CustomObject:
            pass

        with pytest.raises(TypeError, match="is not JSON serializable"):
            JSONResponse({"obj": CustomObject()})


class TestHTMLResponseRenderTemplate:
    """Test HTMLResponse._render_template branches."""

    def test_uses_settings_templates_dir_when_default(self):
        """Should use settings.TEMPLATES_DIR when template_dir is default."""
        mock_settings = MagicMock()
        mock_settings.TEMPLATES_DIR = "/custom/templates"
        mock_settings.INSTALLED_APPS = ()

        mock_env = MagicMock()
        mock_template = MagicMock()
        mock_template.render.return_value = "<html>test</html>"
        mock_env.get_template.return_value = mock_template

        with patch("openviper.http.response.settings", mock_settings):
            with patch("openviper.http.response._get_jinja2_env", return_value=mock_env):
                with patch(
                    "openviper.http.response._compute_template_search_paths"
                ) as mock_compute:
                    mock_compute.return_value = ("/custom/templates",)

                    HTMLResponse(template="test.html")

                    # Should have called with custom templates dir
                    mock_compute.assert_called_once_with("/custom/templates", ())

    def test_uses_explicit_template_dir(self):
        """Should use explicit template_dir when provided."""
        mock_settings = MagicMock()
        mock_settings.TEMPLATES_DIR = "/custom/templates"
        mock_settings.INSTALLED_APPS = ()

        mock_env = MagicMock()
        mock_template = MagicMock()
        mock_template.render.return_value = "<html>test</html>"
        mock_env.get_template.return_value = mock_template

        with patch("openviper.http.response.settings", mock_settings):
            with patch("openviper.http.response._get_jinja2_env", return_value=mock_env):
                with patch(
                    "openviper.http.response._compute_template_search_paths"
                ) as mock_compute:
                    mock_compute.return_value = ("/explicit/path",)

                    HTMLResponse(template="test.html", template_dir="/explicit/path")

                    # Should have called with explicit path
                    mock_compute.assert_called_once_with("/explicit/path", ())

    def test_handles_settings_without_templates_dir(self):
        """Should handle settings without TEMPLATES_DIR attribute."""
        mock_settings = MagicMock(spec=[])  # No TEMPLATES_DIR attribute
        mock_settings.INSTALLED_APPS = ()

        mock_env = MagicMock()
        mock_template = MagicMock()
        mock_template.render.return_value = "<html>test</html>"
        mock_env.get_template.return_value = mock_template

        with patch("openviper.http.response.settings", mock_settings):
            with patch("openviper.http.response._get_jinja2_env", return_value=mock_env):
                with patch(
                    "openviper.http.response._compute_template_search_paths"
                ) as mock_compute:
                    mock_compute.return_value = ("templates",)

                    HTMLResponse(template="test.html")

                    # Should use default "templates" since TEMPLATES_DIR not present
                    mock_compute.assert_called_once_with("templates", ())

    def test_includes_installed_apps_in_search(self):
        """Should include INSTALLED_APPS in template search."""
        mock_settings = MagicMock()
        mock_settings.TEMPLATES_DIR = "/templates"
        mock_settings.INSTALLED_APPS = ("app1", "app2")

        mock_env = MagicMock()
        mock_template = MagicMock()
        mock_template.render.return_value = "<html>test</html>"
        mock_env.get_template.return_value = mock_template

        with patch("openviper.http.response.settings", mock_settings):
            with patch("openviper.http.response._get_jinja2_env", return_value=mock_env):
                with patch(
                    "openviper.http.response._compute_template_search_paths"
                ) as mock_compute:
                    mock_compute.return_value = ("/templates", "/app1/templates", "/app2/templates")

                    HTMLResponse(template="test.html")

                    # Should have passed installed apps as tuple
                    mock_compute.assert_called_once_with("/templates", ("app1", "app2"))


class TestFileResponseConditionalRequests:
    """Test FileResponse conditional request error handling."""

    @pytest.mark.asyncio
    async def test_if_modified_since_malformed_date_ignored(self, tmp_path):
        """Should ignore malformed If-Modified-Since header and serve file."""
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        response = FileResponse(str(test_file))

        # Mock scope with malformed If-Modified-Since header
        scope = {
            "headers": [
                (b"if-modified-since", b"invalid-date-format"),
            ],
        }

        sends = []

        async def mock_send(message):
            sends.append(message)

        async def mock_receive():
            pass

        # Should not raise, should serve the file
        await response(scope, mock_receive, mock_send)

        # Should send full response (not 304)
        assert sends[0]["status"] == 200
        assert sends[1]["body"] == b"test content"

    @pytest.mark.asyncio
    async def test_if_modified_since_type_error_ignored(self, tmp_path):
        """Should handle TypeError when parsing If-Modified-Since."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        response = FileResponse(str(test_file))

        # Mock scope with header that causes TypeError
        scope = {
            "headers": [
                (b"if-modified-since", b"Wed, 21 Oct 2015 07:28:00 XYZ"),  # Invalid timezone
            ],
        }

        sends = []

        async def mock_send(message):
            sends.append(message)

        async def mock_receive():
            pass

        # Should not raise, should serve the file
        await response(scope, mock_receive, mock_send)

        # Should send full response (not 304)
        assert sends[0]["status"] == 200
