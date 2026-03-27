"""Integration tests for OAuth2 authentication event system."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.authentications import OAuth2Authentication

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_user(
    user_id: int = 1,
    email: str = "user@example.com",
    username: str = "testuser",
    is_active: bool = True,
    last_login: Any = None,
) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.username = username
    user.is_active = is_active
    user.last_login = last_login
    return user


class FakeRequest:
    """Minimal ASGI request stub for integration tests."""

    def __init__(self, token: str = "validtoken") -> None:
        self.headers: dict[str, str] = {"authorization": f"Bearer {token}"}
        self.path = "/"
        self._scope: dict[str, Any] = {}
        self.cookies: dict[str, str] = {}
        self.session = None


# ---------------------------------------------------------------------------
# Integration: full login success → on_success fires
# ---------------------------------------------------------------------------


class TestOAuth2LoginSuccessEvent:
    """OAuth2 login success triggers on_success."""

    @pytest.mark.asyncio
    async def test_oauth2_login_success_event(self) -> None:
        on_success_calls: list[dict[str, Any]] = []

        async def handler(payload: dict[str, Any]) -> None:
            on_success_calls.append(payload)

        user = _make_fake_user(last_login=MagicMock())  # not first login

        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {"on_success": "myapp.events.oauth_success"}

        fake_module = MagicMock()
        fake_module.oauth_success = handler

        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch.object(
                OAuth2Authentication,
                "_resolve_oauth2_user",
                new=AsyncMock(return_value=user.id),
            ),
            patch(
                "openviper.auth.authentications.get_user_cached",
                new=AsyncMock(return_value=user),
            ),
            patch("importlib.import_module", return_value=fake_module),
        ):
            auth = OAuth2Authentication()
            result = await auth.authenticate(FakeRequest())

        assert result is not None
        user_returned, info = result
        assert info["type"] == "oauth2"
        assert len(on_success_calls) == 1
        assert on_success_calls[0]["email"] == user.email
        assert on_success_calls[0]["authentication_type"] == "oauth2"

    @pytest.mark.asyncio
    async def test_authentication_succeeds_even_if_on_success_raises(self) -> None:
        async def broken_handler(payload: dict[str, Any]) -> None:
            raise RuntimeError("handler crashed")

        user = _make_fake_user(last_login=MagicMock())

        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {"on_success": "myapp.events.oauth_success"}

        fake_module = MagicMock()
        fake_module.oauth_success = broken_handler

        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch.object(
                OAuth2Authentication,
                "_resolve_oauth2_user",
                new=AsyncMock(return_value=user.id),
            ),
            patch(
                "openviper.auth.authentications.get_user_cached",
                new=AsyncMock(return_value=user),
            ),
            patch("importlib.import_module", return_value=fake_module),
        ):
            auth = OAuth2Authentication()
            result = await auth.authenticate(FakeRequest())

        # Authentication must succeed regardless of the event handler crash.
        assert result is not None


# ---------------------------------------------------------------------------
# Integration: login failure → on_fail fires
# ---------------------------------------------------------------------------


class TestOAuth2LoginFailEvent:
    """OAuth2 on_fail event fires when authentication is unsuccessful."""

    @pytest.mark.asyncio
    async def test_on_fail_fires_when_token_invalid(self) -> None:
        on_fail_calls: list[dict[str, Any]] = []

        def handler(payload: dict[str, Any]) -> None:
            on_fail_calls.append(payload)

        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {"on_fail": "myapp.events.oauth_fail"}

        fake_module = MagicMock()
        fake_module.oauth_fail = handler

        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch("importlib.import_module", return_value=fake_module),
            # Token resolves to no user (invalid / expired)
            patch.object(
                OAuth2Authentication,
                "_resolve_oauth2_user",
                new=AsyncMock(return_value=None),
            ),
        ):
            auth = OAuth2Authentication()
            result = await auth.authenticate(FakeRequest())

        assert result is None
        assert len(on_fail_calls) == 1

    @pytest.mark.asyncio
    async def test_on_fail_fires_when_user_inactive(self) -> None:
        on_fail_calls: list[dict[str, Any]] = []

        def handler(payload: dict[str, Any]) -> None:
            on_fail_calls.append(payload)

        inactive_user = _make_fake_user(is_active=False)

        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {"on_fail": "myapp.events.oauth_fail"}

        fake_module = MagicMock()
        fake_module.oauth_fail = handler

        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch.object(
                OAuth2Authentication,
                "_resolve_oauth2_user",
                new=AsyncMock(return_value=inactive_user.id),
            ),
            patch(
                "openviper.auth.authentications.get_user_cached",
                new=AsyncMock(return_value=inactive_user),
            ),
            patch("importlib.import_module", return_value=fake_module),
        ):
            auth = OAuth2Authentication()
            result = await auth.authenticate(FakeRequest())

        assert result is None
        assert len(on_fail_calls) == 1

    @pytest.mark.asyncio
    async def test_returns_none_with_no_auth_header(self) -> None:
        auth = OAuth2Authentication()
        request = FakeRequest()
        request.headers = {}
        result = await auth.authenticate(request)
        assert result is None


# ---------------------------------------------------------------------------
# Integration: first login → on_initial fires
# ---------------------------------------------------------------------------


class TestOAuth2FirstLoginEvent:
    """OAuth2 on_initial fires only on the very first login."""

    @pytest.mark.asyncio
    async def test_on_initial_fires_for_new_user(self) -> None:
        initial_calls: list[dict[str, Any]] = []
        success_calls: list[dict[str, Any]] = []

        def on_initial(payload: dict[str, Any]) -> None:
            initial_calls.append(payload)

        def on_success(payload: dict[str, Any]) -> None:
            success_calls.append(payload)

        # last_login is None → first login
        new_user = _make_fake_user(last_login=None)

        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {
            "on_initial": "myapp.events.oauth_initial",
            "on_success": "myapp.events.oauth_success",
        }

        def fake_import(name: str, *args: Any, **kwargs: Any) -> MagicMock:
            m = MagicMock()
            m.oauth_initial = on_initial
            m.oauth_success = on_success
            return m

        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch.object(
                OAuth2Authentication,
                "_resolve_oauth2_user",
                new=AsyncMock(return_value=new_user.id),
            ),
            patch(
                "openviper.auth.authentications.get_user_cached",
                new=AsyncMock(return_value=new_user),
            ),
            patch("importlib.import_module", side_effect=fake_import),
        ):
            auth = OAuth2Authentication()
            result = await auth.authenticate(FakeRequest())

        assert result is not None
        assert len(initial_calls) == 1
        assert len(success_calls) == 1

    @pytest.mark.asyncio
    async def test_on_initial_does_not_fire_for_returning_user(self) -> None:
        initial_calls: list[dict[str, Any]] = []

        def on_initial(payload: dict[str, Any]) -> None:
            initial_calls.append(payload)

        # last_login is set → returning user
        returning_user = _make_fake_user(last_login=MagicMock())

        mock_settings = MagicMock()
        mock_settings.OAUTH2_EVENTS = {"on_initial": "myapp.events.oauth_initial"}

        fake_module = MagicMock()
        fake_module.oauth_initial = on_initial

        with (
            patch("openviper.auth.authentications.settings", mock_settings),
            patch.object(
                OAuth2Authentication,
                "_resolve_oauth2_user",
                new=AsyncMock(return_value=returning_user.id),
            ),
            patch(
                "openviper.auth.authentications.get_user_cached",
                new=AsyncMock(return_value=returning_user),
            ),
            patch("importlib.import_module", return_value=fake_module),
        ):
            auth = OAuth2Authentication()
            await auth.authenticate(FakeRequest())

        assert len(initial_calls) == 0
