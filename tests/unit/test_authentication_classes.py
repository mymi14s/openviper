"""Unit tests for openviper.auth.authentications."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.authentications import JWTAuthentication, SessionAuthentication
from openviper.auth.jwt import create_access_token
from openviper.auth.models import AnonymousUser
from openviper.auth.session.store import Session


class FakeRequest:
    """Minimal request mock for authentication tests."""

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        scope_user: object | None = None,
        session: Session | None = None,
    ) -> None:
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.path = "/"
        self.method = "GET"
        self._scope: dict = {}
        if scope_user is not None:
            self._scope["user"] = scope_user
        self._session = session

    @property
    def session(self) -> Session:
        if self._session is not None:
            return self._session
        return Session(key="")


@pytest.mark.asyncio
class TestJWTAuthentication:
    async def test_authenticate_success(self) -> None:
        token = create_access_token(user_id=42)
        request = FakeRequest(headers={"authorization": f"Bearer {token}"})
        fake_user = MagicMock()
        fake_user.is_active = True

        with patch(
            "openviper.auth.authentications.get_user_cached", new=AsyncMock(return_value=fake_user)
        ):
            with patch(
                "openviper.auth.authentications.is_token_revoked", new=AsyncMock(return_value=False)
            ):
                auth = JWTAuthentication()
                result = await auth.authenticate(request)

                assert result is not None
                user, auth_info = result
                assert user is fake_user
                assert auth_info["type"] == "jwt"
                assert auth_info["token"] == token

    async def test_authenticate_no_header(self) -> None:
        request = FakeRequest()
        auth = JWTAuthentication()
        result = await auth.authenticate(request)
        assert result is None

    async def test_authenticate_invalid_header(self) -> None:
        request = FakeRequest(headers={"authorization": "Basic base64"})
        auth = JWTAuthentication()
        result = await auth.authenticate(request)
        assert result is None


@pytest.mark.asyncio
class TestSessionAuthentication:
    async def test_authenticate_via_scope_user_fast_path(self) -> None:
        """When SessionMiddleware already set scope['user'], use it directly."""
        fake_user = MagicMock()
        fake_user.is_authenticated = True
        fake_user.is_active = True

        request = FakeRequest(scope_user=fake_user)
        auth = SessionAuthentication()
        result = await auth.authenticate(request)

        assert result is not None
        user, auth_info = result
        assert user is fake_user
        assert auth_info["type"] == "session"

    async def test_authenticate_fallback_via_session_store(self) -> None:
        """When scope user is not set, fall back to session store lookup."""
        fake_user = MagicMock()
        fake_user.is_active = True

        mock_store = MagicMock()
        mock_store.get_user = AsyncMock(return_value=fake_user)
        session = Session(key="valid-key-" + "x" * 50, data={"user_id": "1"}, store=mock_store)

        request = FakeRequest(session=session)
        auth = SessionAuthentication()

        with patch("openviper.auth.authentications.get_session_store", return_value=mock_store):
            result = await auth.authenticate(request)

        assert result is not None
        user, auth_info = result
        assert user is fake_user
        assert auth_info["type"] == "session"
        mock_store.get_user.assert_awaited_once()

    async def test_authenticate_cookie_fallback_without_session_middleware(self) -> None:
        """When no SessionMiddleware populates request.session, load session
        directly from cookie so SessionAuthentication works standalone."""
        fake_user = MagicMock()
        fake_user.is_active = True

        mock_store = MagicMock()
        mock_store.get_user = AsyncMock(return_value=fake_user)

        # No session on request, but cookie is present
        request = FakeRequest(cookies={"sessionid": "cookie-session-key"})
        auth = SessionAuthentication()

        with patch("openviper.auth.authentications.get_session_store", return_value=mock_store):
            result = await auth.authenticate(request)

        assert result is not None
        user, auth_info = result
        assert user is fake_user
        assert auth_info["type"] == "session"
        mock_store.get_user.assert_awaited_once_with("cookie-session-key")

    async def test_authenticate_no_session(self) -> None:
        """No session cookie returns None."""
        request = FakeRequest()
        auth = SessionAuthentication()
        result = await auth.authenticate(request)
        assert result is None

    async def test_authenticate_inactive_scope_user_skipped(self) -> None:
        """Inactive scope user should not be returned."""
        fake_user = MagicMock()
        fake_user.is_authenticated = True
        fake_user.is_active = False

        request = FakeRequest(scope_user=fake_user)
        auth = SessionAuthentication()
        result = await auth.authenticate(request)
        assert result is None

    async def test_authenticate_anonymous_scope_user_falls_through(self) -> None:
        """AnonymousUser in scope should not trigger fast path."""
        request = FakeRequest(scope_user=AnonymousUser())
        auth = SessionAuthentication()
        result = await auth.authenticate(request)
        assert result is None
