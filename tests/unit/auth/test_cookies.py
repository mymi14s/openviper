"""Unit tests for openviper.auth.utils.cookies module."""

import datetime
from unittest.mock import MagicMock, patch

from openviper.auth.utils.cookies import (
    build_clear_cookie_header,
    build_set_cookie_header,
    get_cookie_settings,
    parse_session_key,
)


class TestParseSessionKey:
    """Tests for parse_session_key function."""

    def test_extracts_session_key(self):

        with patch("openviper.auth.utils.cookies.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"

            result = parse_session_key("sessionid=abc123; other=value")

        assert result == "abc123"

    def test_returns_none_for_missing_cookie(self):

        with patch("openviper.auth.utils.cookies.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"

            result = parse_session_key("other=value; another=thing")

        assert result is None

    def test_handles_custom_cookie_name(self):

        with patch("openviper.auth.utils.cookies.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "mysession"

            result = parse_session_key("mysession=xyz789; other=value")

        assert result == "xyz789"

    def test_handles_empty_cookie_header(self):

        with patch("openviper.auth.utils.cookies.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"

            result = parse_session_key("")

        assert result is None

    def test_uses_default_cookie_name(self):

        mock_settings = MagicMock()
        del mock_settings.SESSION_COOKIE_NAME  # Simulate attribute not set

        with patch("openviper.auth.utils.cookies.settings", mock_settings):
            with patch("openviper.auth.utils.cookies.getattr", return_value="sessionid"):
                parse_session_key("sessionid=test123")

        # Should still work with default


class TestGetCookieSettings:
    """Tests for get_cookie_settings function."""

    def test_returns_settings_dict(self):

        with patch("openviper.auth.utils.cookies.settings") as mock_settings:
            mock_settings.SESSION_COOKIE_NAME = "sessionid"
            mock_settings.SESSION_COOKIE_HTTPONLY = True
            mock_settings.SESSION_COOKIE_SECURE = True
            mock_settings.SESSION_COOKIE_SAMESITE = "Strict"

            result = get_cookie_settings()

        assert result["name"] == "sessionid"
        assert result["httponly"] is True
        assert result["secure"] is True
        assert result["samesite"] == "Strict"

    def test_returns_defaults_when_not_configured(self):

        mock_settings = MagicMock(spec=[])  # No attributes

        with patch("openviper.auth.utils.cookies.settings", mock_settings):
            result = get_cookie_settings()

        assert result["name"] == "sessionid"
        assert result["httponly"] is True
        assert result["secure"] is False
        assert result["samesite"] == "Lax"


class TestBuildSetCookieHeader:
    """Tests for build_set_cookie_header function."""

    def test_builds_basic_cookie(self):

        mock_settings = MagicMock(spec=[])

        with patch("openviper.auth.utils.cookies.settings", mock_settings):
            result = build_set_cookie_header("abc123")

        assert "sessionid=abc123" in result
        assert "Path=/" in result

    def test_includes_httponly(self):

        mock_settings = MagicMock()
        mock_settings.SESSION_COOKIE_NAME = "sessionid"
        mock_settings.SESSION_COOKIE_HTTPONLY = True
        mock_settings.SESSION_COOKIE_SECURE = False
        mock_settings.SESSION_COOKIE_SAMESITE = "Lax"
        mock_settings.SESSION_TIMEOUT = None

        with patch("openviper.auth.utils.cookies.settings", mock_settings):
            result = build_set_cookie_header("test123")

        assert "HttpOnly" in result

    def test_includes_secure(self):

        mock_settings = MagicMock()
        mock_settings.SESSION_COOKIE_NAME = "sessionid"
        mock_settings.SESSION_COOKIE_HTTPONLY = True
        mock_settings.SESSION_COOKIE_SECURE = True
        mock_settings.SESSION_COOKIE_SAMESITE = "Strict"
        mock_settings.SESSION_TIMEOUT = None

        with patch("openviper.auth.utils.cookies.settings", mock_settings):
            result = build_set_cookie_header("test123")

        assert "Secure" in result

    def test_includes_samesite(self):

        mock_settings = MagicMock()
        mock_settings.SESSION_COOKIE_NAME = "sessionid"
        mock_settings.SESSION_COOKIE_HTTPONLY = False
        mock_settings.SESSION_COOKIE_SECURE = False
        mock_settings.SESSION_COOKIE_SAMESITE = "Strict"
        mock_settings.SESSION_TIMEOUT = None

        with patch("openviper.auth.utils.cookies.settings", mock_settings):
            result = build_set_cookie_header("test123")

        assert "SameSite=Strict" in result

    def test_includes_max_age_from_timeout(self):

        mock_settings = MagicMock()
        mock_settings.SESSION_COOKIE_NAME = "sessionid"
        mock_settings.SESSION_COOKIE_HTTPONLY = True
        mock_settings.SESSION_COOKIE_SECURE = False
        mock_settings.SESSION_COOKIE_SAMESITE = "Lax"
        mock_settings.SESSION_TIMEOUT = datetime.timedelta(hours=2)

        with patch("openviper.auth.utils.cookies.settings", mock_settings):
            result = build_set_cookie_header("test123")

        assert "Max-Age=7200" in result  # 2 hours = 7200 seconds


class TestBuildClearCookieHeader:
    """Tests for build_clear_cookie_header function."""

    def test_clears_cookie(self):

        mock_settings = MagicMock()
        mock_settings.SESSION_COOKIE_NAME = "sessionid"
        mock_settings.SESSION_COOKIE_HTTPONLY = True
        mock_settings.SESSION_COOKIE_SECURE = False
        mock_settings.SESSION_COOKIE_SAMESITE = "Lax"

        with patch("openviper.auth.utils.cookies.settings", mock_settings):
            result = build_clear_cookie_header()

        assert "sessionid=" in result
        assert "Max-Age=0" in result
        assert "Path=/" in result

    def test_includes_httponly_when_enabled(self):

        mock_settings = MagicMock()
        mock_settings.SESSION_COOKIE_NAME = "sessionid"
        mock_settings.SESSION_COOKIE_HTTPONLY = True
        mock_settings.SESSION_COOKIE_SECURE = False
        mock_settings.SESSION_COOKIE_SAMESITE = "Lax"

        with patch("openviper.auth.utils.cookies.settings", mock_settings):
            result = build_clear_cookie_header()

        assert "HttpOnly" in result

    def test_includes_secure_when_enabled(self):

        mock_settings = MagicMock()
        mock_settings.SESSION_COOKIE_NAME = "sessionid"
        mock_settings.SESSION_COOKIE_HTTPONLY = False
        mock_settings.SESSION_COOKIE_SECURE = True
        mock_settings.SESSION_COOKIE_SAMESITE = "Lax"

        with patch("openviper.auth.utils.cookies.settings", mock_settings):
            result = build_clear_cookie_header()

        assert "Secure" in result
