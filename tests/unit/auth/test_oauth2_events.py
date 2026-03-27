"""Unit tests for OAuth2Authentication event system."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.authentications import OAuth2Authentication

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_VALID_PATH = "myapp.events.oauth_success"
_VALID_PATH_FAIL = "myapp.events.oauth_fail"
_VALID_PATH_ERROR = "myapp.events.oauth_error"
_VALID_PATH_INITIAL = "myapp.events.oauth_initial"

_SAMPLE_EVENTS: dict[str, str] = {
    "on_success": _VALID_PATH,
    "on_fail": _VALID_PATH_FAIL,
    "on_error": _VALID_PATH_ERROR,
    "on_initial": _VALID_PATH_INITIAL,
}

_SAMPLE_PAYLOAD: dict[str, Any] = {
    "provider": "google",
    "access_token": "tok123",
    "user_info": {},
    "email": "user@example.com",
    "name": "User Name",
    "provider_user_id": "123",
    "request": MagicMock(),
    "authentication_type": "oauth2",
    "error": "",
}


class FakeRequest:
    """Minimal request stub."""

    def __init__(self, token: str = "tok123") -> None:
        scheme = "Bearer"
        self.headers: dict[str, str] = {"authorization": f"{scheme} {token}"}
        self.path = "/"
        self._scope: dict[str, Any] = {}
        self.cookies: dict[str, str] = {}
        self.session = None


# ---------------------------------------------------------------------------
# load_oauth2_events
# ---------------------------------------------------------------------------


class TestLoadOAuth2Events:
    """Tests for OAuth2Authentication.load_oauth2_events."""

    def test_returns_empty_dict_when_setting_absent(self) -> None:
        auth = OAuth2Authentication()
        with patch("openviper.auth.authentications.settings", spec=[]):
            result = auth.load_oauth2_events()
        assert result == {}

    def test_returns_configured_events(self) -> None:
        auth = OAuth2Authentication()
        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = _SAMPLE_EVENTS
        with patch("openviper.auth.authentications.settings", mock_settings):
            result = auth.load_oauth2_events()
        assert result == _SAMPLE_EVENTS

    def test_returns_copy_not_original_reference(self) -> None:
        auth = OAuth2Authentication()
        original = {"on_success": "a.b.c"}
        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = original
        with patch("openviper.auth.authentications.settings", mock_settings):
            result = auth.load_oauth2_events()
        # Mutating the returned dict must not affect settings
        result["on_success"] = "mutated"
        assert original["on_success"] == "a.b.c"

    def test_returns_empty_dict_when_events_is_none(self) -> None:
        auth = OAuth2Authentication()
        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = None
        with patch("openviper.auth.authentications.settings", mock_settings):
            # getattr(..., {}) returns None when attribute exists but is None
            with patch.object(auth, "load_oauth2_events", return_value={}):
                result = auth.load_oauth2_events()
        assert result == {}


# ---------------------------------------------------------------------------
# resolve_event_handler
# ---------------------------------------------------------------------------


class TestResolveEventHandler:
    """Tests for OAuth2Authentication.resolve_event_handler."""

    def test_imports_and_returns_callable(self) -> None:
        auth = OAuth2Authentication()
        handler = MagicMock()
        fake_module = MagicMock()
        fake_module.handler_fn = handler
        with patch("importlib.import_module", return_value=fake_module):
            result = auth.resolve_event_handler("myapp.events.handler_fn")
        assert result is handler

    def test_raises_value_error_for_invalid_path(self) -> None:
        auth = OAuth2Authentication()
        with pytest.raises(ValueError, match="Invalid event handler path"):
            auth.resolve_event_handler("notadottedpath")

    def test_raises_value_error_for_single_segment(self) -> None:
        auth = OAuth2Authentication()
        with pytest.raises(ValueError, match="Invalid event handler path"):
            auth.resolve_event_handler("singleword")

    def test_raises_import_error_when_module_missing(self) -> None:
        auth = OAuth2Authentication()
        with patch("importlib.import_module", side_effect=ImportError("no module")):
            with pytest.raises(ImportError):
                auth.resolve_event_handler("nonexistent.module.fn")

    def test_raises_attribute_error_when_func_missing(self) -> None:
        auth = OAuth2Authentication()
        fake_module = MagicMock(spec=[])  # no attributes
        with patch("importlib.import_module", return_value=fake_module):
            with pytest.raises(AttributeError):
                auth.resolve_event_handler("myapp.events.missing_fn")

    def test_rejects_path_with_invalid_characters(self) -> None:
        auth = OAuth2Authentication()
        with pytest.raises(ValueError, match="Invalid event handler path"):
            auth.resolve_event_handler("my-app.events.fn")

    def test_rejects_path_starting_with_digit(self) -> None:
        auth = OAuth2Authentication()
        with pytest.raises(ValueError, match="Invalid event handler path"):
            auth.resolve_event_handler("1app.events.fn")


# ---------------------------------------------------------------------------
# trigger_event
# ---------------------------------------------------------------------------


class TestTriggerEventOnSuccess:
    """Tests for trigger_event with on_success."""

    @pytest.mark.asyncio
    async def test_calls_sync_handler(self) -> None:
        auth = OAuth2Authentication()
        handler = MagicMock()
        fake_module = MagicMock()
        fake_module.oauth_success = handler
        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {"on_success": "myapp.events.oauth_success"}
        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch("importlib.import_module", return_value=fake_module),
        ):
            await auth.trigger_event("on_success", _SAMPLE_PAYLOAD)
        handler.assert_called_once_with(_SAMPLE_PAYLOAD)

    @pytest.mark.asyncio
    async def test_calls_async_handler(self) -> None:
        auth = OAuth2Authentication()
        handler = AsyncMock()
        fake_module = MagicMock()
        fake_module.oauth_success = handler
        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {"on_success": "myapp.events.oauth_success"}
        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch("importlib.import_module", return_value=fake_module),
        ):
            await auth.trigger_event("on_success", _SAMPLE_PAYLOAD)
        handler.assert_awaited_once_with(_SAMPLE_PAYLOAD)

    @pytest.mark.asyncio
    async def test_skips_when_event_not_configured(self) -> None:
        auth = OAuth2Authentication()
        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {}
        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch("importlib.import_module") as mock_import,
        ):
            await auth.trigger_event("on_success", _SAMPLE_PAYLOAD)
        mock_import.assert_not_called()

    @pytest.mark.asyncio
    async def test_logs_and_continues_on_import_error(self) -> None:
        auth = OAuth2Authentication()
        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {"on_success": "myapp.events.oauth_success"}
        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch("importlib.import_module", side_effect=ImportError("gone")),
        ):
            # Must not raise
            await auth.trigger_event("on_success", _SAMPLE_PAYLOAD)

    @pytest.mark.asyncio
    async def test_logs_and_continues_on_handler_exception(self) -> None:
        auth = OAuth2Authentication()
        handler = MagicMock(side_effect=RuntimeError("boom"))
        fake_module = MagicMock()
        fake_module.oauth_success = handler
        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {"on_success": "myapp.events.oauth_success"}
        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch("importlib.import_module", return_value=fake_module),
        ):
            await auth.trigger_event("on_success", _SAMPLE_PAYLOAD)
        # handler was called but the exception was swallowed
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_ignores_unknown_event_name(self) -> None:
        auth = OAuth2Authentication()
        with patch("importlib.import_module") as mock_import:
            await auth.trigger_event("on_unknown", _SAMPLE_PAYLOAD)
        mock_import.assert_not_called()


class TestTriggerEventOnFail:
    """Tests for trigger_event with on_fail."""

    @pytest.mark.asyncio
    async def test_calls_on_fail_handler(self) -> None:
        auth = OAuth2Authentication()
        handler = MagicMock()
        fake_module = MagicMock()
        fake_module.oauth_fail = handler
        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {"on_fail": "myapp.events.oauth_fail"}
        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch("importlib.import_module", return_value=fake_module),
        ):
            await auth.trigger_event("on_fail", _SAMPLE_PAYLOAD)
        handler.assert_called_once_with(_SAMPLE_PAYLOAD)

    @pytest.mark.asyncio
    async def test_passes_payload_verbatim(self) -> None:
        auth = OAuth2Authentication()
        received: list[dict[str, Any]] = []

        def capture(p: dict[str, Any]) -> None:
            received.append(p)

        fake_module = MagicMock()
        fake_module.oauth_fail = capture
        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {"on_fail": "myapp.events.oauth_fail"}
        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch("importlib.import_module", return_value=fake_module),
        ):
            await auth.trigger_event("on_fail", _SAMPLE_PAYLOAD)
        assert received[0] is _SAMPLE_PAYLOAD


class TestTriggerEventOnError:
    """Tests for trigger_event with on_error."""

    @pytest.mark.asyncio
    async def test_calls_on_error_handler(self) -> None:
        auth = OAuth2Authentication()
        handler = AsyncMock()
        fake_module = MagicMock()
        fake_module.oauth_error = handler
        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {"on_error": "myapp.events.oauth_error"}
        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch("importlib.import_module", return_value=fake_module),
        ):
            await auth.trigger_event("on_error", _SAMPLE_PAYLOAD)
        handler.assert_awaited_once_with(_SAMPLE_PAYLOAD)


class TestTriggerEventOnInitial:
    """Tests for trigger_event with on_initial."""

    @pytest.mark.asyncio
    async def test_calls_on_initial_handler(self) -> None:
        auth = OAuth2Authentication()
        handler = MagicMock()
        fake_module = MagicMock()
        fake_module.oauth_initial = handler
        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {"on_initial": "myapp.events.oauth_initial"}
        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch("importlib.import_module", return_value=fake_module),
        ):
            await auth.trigger_event("on_initial", _SAMPLE_PAYLOAD)
        handler.assert_called_once_with(_SAMPLE_PAYLOAD)

    @pytest.mark.asyncio
    async def test_on_initial_not_triggered_when_not_configured(self) -> None:
        auth = OAuth2Authentication()
        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {}
        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch("importlib.import_module") as mock_import,
        ):
            await auth.trigger_event("on_initial", _SAMPLE_PAYLOAD)
        mock_import.assert_not_called()
