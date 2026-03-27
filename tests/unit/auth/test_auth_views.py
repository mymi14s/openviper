"""Unit tests for the consolidated auth views and route lists.

Covers openviper.auth.views.base_login, jwt_login, token_login, session_login,
logout, me, and routes modules.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import openviper.auth as auth_package
from openviper.auth.views.base_login import BaseLoginView
from openviper.auth.views.jwt_login import JWTLoginView
from openviper.auth.views.logout import LogoutView
from openviper.auth.views.me import MeView
from openviper.auth.views.routes import all_auth_routes, jwt_routes, session_routes, token_routes
from openviper.auth.views.session_login import SessionLoginView
from openviper.auth.views.token_login import TokenLoginView
from openviper.exceptions import Unauthorized

# ---------------------------------------------------------------------------
# Shared request stub
# ---------------------------------------------------------------------------


def _make_request(
    json_body: dict | None = None,
    auth: dict | None = None,
    user: object | None = None,
    cookies: dict | None = None,
) -> MagicMock:
    """Return a minimal async-capable request mock."""
    req = MagicMock()
    req.json = AsyncMock(return_value=json_body or {})
    req.auth = auth or {"type": "none"}
    req.user = user
    req.cookies = cookies or {}
    req._session = None
    req._scope = {}
    return req


def _make_user(pk: int = 1, username: str = "alice") -> MagicMock:
    """Return a minimal user stub."""
    user = MagicMock()
    user.pk = pk
    user.username = username
    user.email = "alice@example.com"
    user.first_name = "Alice"
    user.last_name = "Liddell"
    user.is_active = True
    user.is_staff = False
    user.is_superuser = False
    user.is_authenticated = True
    return user


# ---------------------------------------------------------------------------
# BaseLoginView.authenticate_user
# ---------------------------------------------------------------------------


class TestBaseLoginViewAuthenticateUser:
    """Tests for BaseLoginView.authenticate_user helper."""

    @pytest.mark.asyncio
    async def test_raises_unauthorized_on_broken_json(self) -> None:
        """Malformed request body raises Unauthorized."""
        view = BaseLoginView()
        req = MagicMock()
        req.json = AsyncMock(side_effect=ValueError("bad json"))
        with pytest.raises(Unauthorized, match="Invalid request body"):
            await view.authenticate_user(req)

    @pytest.mark.asyncio
    async def test_raises_unauthorized_when_username_missing(self) -> None:
        """Missing username field raises Unauthorized."""
        view = BaseLoginView()
        req = _make_request(json_body={"password": "secret"})
        with pytest.raises(Unauthorized, match="required"):
            await view.authenticate_user(req)

    @pytest.mark.asyncio
    async def test_raises_unauthorized_when_password_missing(self) -> None:
        """Missing password field raises Unauthorized."""
        view = BaseLoginView()
        req = _make_request(json_body={"username": "alice"})
        with pytest.raises(Unauthorized, match="required"):
            await view.authenticate_user(req)

    @pytest.mark.asyncio
    async def test_raises_unauthorized_when_both_fields_empty(self) -> None:
        """Empty username and password raise Unauthorized."""
        view = BaseLoginView()
        req = _make_request(json_body={"username": "", "password": ""})
        with pytest.raises(Unauthorized, match="required"):
            await view.authenticate_user(req)

    @pytest.mark.asyncio
    async def test_raises_unauthorized_when_authenticate_returns_none(self) -> None:
        """Invalid credentials (authenticate returns None) raise Unauthorized."""
        view = BaseLoginView()
        req = _make_request(json_body={"username": "bob", "password": "wrong"})
        with patch(
            "openviper.auth.views.base_login.authenticate",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(Unauthorized, match="Invalid credentials"):
                await view.authenticate_user(req)

    @pytest.mark.asyncio
    async def test_raises_unauthorized_when_account_inactive(self) -> None:
        """Inactive account raises Unauthorized even when credentials are correct."""
        view = BaseLoginView()
        inactive_user = _make_user()
        inactive_user.is_active = False
        req = _make_request(json_body={"username": "alice", "password": "correct"})
        with patch(
            "openviper.auth.views.base_login.authenticate",
            new_callable=AsyncMock,
            return_value=inactive_user,
        ):
            with pytest.raises(Unauthorized, match="inactive"):
                await view.authenticate_user(req)

    @pytest.mark.asyncio
    async def test_returns_user_on_valid_credentials(self) -> None:
        """Valid credentials return the user object."""
        view = BaseLoginView()
        user = _make_user()
        req = _make_request(json_body={"username": "alice", "password": "correct"})
        with patch(
            "openviper.auth.views.base_login.authenticate",
            new_callable=AsyncMock,
            return_value=user,
        ):
            result = await view.authenticate_user(req)
        assert result is user


# ---------------------------------------------------------------------------
# JWTLoginView
# ---------------------------------------------------------------------------


class TestJWTLoginView:
    """Tests for JWTLoginView.post."""

    @pytest.mark.asyncio
    async def test_returns_access_and_refresh_tokens(self) -> None:
        """Successful login returns both access and refresh tokens."""
        view = JWTLoginView()
        user = _make_user(pk=7)
        req = _make_request(json_body={"username": "alice", "password": "pw"})

        with (
            patch.object(view, "authenticate_user", new_callable=AsyncMock, return_value=user),
            patch(
                "openviper.auth.views.jwt_login.create_access_token", return_value="acc.tok"
            ) as m_acc,
            patch(
                "openviper.auth.views.jwt_login.create_refresh_token", return_value="ref.tok"
            ) as m_ref,
        ):
            result = await view.post(req)

        m_acc.assert_called_once_with(user_id=7)
        m_ref.assert_called_once_with(user_id=7)
        assert result == {"access": "acc.tok", "refresh": "ref.tok"}

    @pytest.mark.asyncio
    async def test_propagates_unauthorized_from_authenticate_user(self) -> None:
        """Unauthorized raised in authenticate_user propagates to the caller."""
        view = JWTLoginView()
        req = _make_request(json_body={"username": "x", "password": "y"})
        with patch.object(
            view, "authenticate_user", new_callable=AsyncMock, side_effect=Unauthorized("bad")
        ):
            with pytest.raises(Unauthorized):
                await view.post(req)


# ---------------------------------------------------------------------------
# TokenLoginView
# ---------------------------------------------------------------------------


class TestTokenLoginView:
    """Tests for TokenLoginView.post."""

    @pytest.mark.asyncio
    async def test_returns_opaque_token(self) -> None:
        """Successful login returns a single opaque token."""
        view = TokenLoginView()
        user = _make_user(pk=3)
        req = _make_request(json_body={"username": "alice", "password": "pw"})

        fake_record: dict = {"id": 1, "key_hash": "abc", "user_id": 3}
        with (
            patch.object(view, "authenticate_user", new_callable=AsyncMock, return_value=user),
            patch(
                "openviper.auth.views.token_login.create_token",
                new_callable=AsyncMock,
                return_value=("raw_tok", fake_record),
            ) as m_create,
        ):
            result = await view.post(req)

        m_create.assert_called_once_with(user_id=3)
        assert result == {"token": "raw_tok"}

    @pytest.mark.asyncio
    async def test_propagates_unauthorized_from_authenticate_user(self) -> None:
        """Unauthorized raised in authenticate_user propagates to the caller."""
        view = TokenLoginView()
        req = _make_request(json_body={"username": "x", "password": "y"})
        with patch.object(
            view, "authenticate_user", new_callable=AsyncMock, side_effect=Unauthorized("bad")
        ):
            with pytest.raises(Unauthorized):
                await view.post(req)


# ---------------------------------------------------------------------------
# SessionLoginView
# ---------------------------------------------------------------------------


class TestSessionLoginView:
    """Tests for SessionLoginView.post."""

    @pytest.mark.asyncio
    async def test_sets_session_cookie_and_returns_detail(self) -> None:
        """Successful login sets a session cookie and returns confirmation."""
        view = SessionLoginView()
        user = _make_user(pk=5)
        req = _make_request(json_body={"username": "alice", "password": "pw"})

        mock_manager = MagicMock()
        mock_manager.login = AsyncMock(return_value="new-session-key-123")

        with (
            patch.object(view, "authenticate_user", new_callable=AsyncMock, return_value=user),
            patch("openviper.auth.views.session_login.SessionManager", return_value=mock_manager),
        ):
            response = await view.post(req)

        mock_manager.login.assert_called_once_with(req, user)
        assert response.status_code == 200
        body = response.body
        assert b"Logged in" in body

    @pytest.mark.asyncio
    async def test_propagates_unauthorized_from_authenticate_user(self) -> None:
        """Unauthorized raised in authenticate_user propagates to the caller."""
        view = SessionLoginView()
        req = _make_request(json_body={"username": "x", "password": "y"})
        with patch.object(
            view, "authenticate_user", new_callable=AsyncMock, side_effect=Unauthorized("bad")
        ):
            with pytest.raises(Unauthorized):
                await view.post(req)


# ---------------------------------------------------------------------------
# LogoutView
# ---------------------------------------------------------------------------


class TestLogoutViewAuthTypeNone:
    """Unauthenticated requests must be rejected."""

    @pytest.mark.asyncio
    async def test_raises_unauthorized_for_anonymous_request(self) -> None:
        """Unauthenticated request raises Unauthorized."""
        view = LogoutView()
        req = _make_request(auth={"type": "none"})
        with pytest.raises(Unauthorized):
            await view.post(req)


class TestLogoutViewJWT:
    """JWT revocation path."""

    @pytest.mark.asyncio
    async def test_revokes_jwt_with_valid_claims(self) -> None:
        """Valid JWT token is blocklisted by jti."""
        view = LogoutView()
        req = _make_request(auth={"type": "jwt", "token": "header.payload.sig"})

        claims = {
            "jti": "some-uuid",
            "type": "access",
            "sub": "42",
            "exp": 9999999999,
        }
        with (
            patch("openviper.auth.views.logout.decode_token_unverified", return_value=claims),
            patch(
                "openviper.auth.views.logout.revoke_jwt_token", new_callable=AsyncMock
            ) as m_revoke,
        ):
            result = await view.post(req)

        m_revoke.assert_called_once()
        call_kwargs = m_revoke.call_args.kwargs
        assert call_kwargs["jti"] == "some-uuid"
        assert call_kwargs["token_type"] == "access"
        assert call_kwargs["user_id"] == "42"
        assert isinstance(call_kwargs["expires_at"], datetime.datetime)
        assert result == {"detail": "Logged out."}

    @pytest.mark.asyncio
    async def test_skips_revocation_when_token_missing(self) -> None:
        """Missing token in auth_info skips JWT revocation silently."""
        view = LogoutView()
        req = _make_request(auth={"type": "jwt", "token": ""})
        with patch(
            "openviper.auth.views.logout.revoke_jwt_token", new_callable=AsyncMock
        ) as m_revoke:
            result = await view.post(req)
        m_revoke.assert_not_called()
        assert result == {"detail": "Logged out."}

    @pytest.mark.asyncio
    async def test_skips_revocation_when_jti_missing(self) -> None:
        """Empty claims (malformed token) skips revocation silently."""
        view = LogoutView()
        req = _make_request(auth={"type": "jwt", "token": "bad.token"})
        with (
            patch("openviper.auth.views.logout.decode_token_unverified", return_value={}),
            patch(
                "openviper.auth.views.logout.revoke_jwt_token", new_callable=AsyncMock
            ) as m_revoke,
        ):
            result = await view.post(req)
        m_revoke.assert_not_called()
        assert result == {"detail": "Logged out."}

    @pytest.mark.asyncio
    async def test_exp_as_datetime_object_is_accepted(self) -> None:
        """exp claim that is already a datetime is used as-is."""
        view = LogoutView()
        req = _make_request(auth={"type": "jwt", "token": "tok"})
        exp_dt = datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC)
        claims = {"jti": "j1", "type": "access", "sub": "1", "exp": exp_dt}
        with (
            patch("openviper.auth.views.logout.decode_token_unverified", return_value=claims),
            patch(
                "openviper.auth.views.logout.revoke_jwt_token", new_callable=AsyncMock
            ) as m_revoke,
        ):
            await view.post(req)
        assert m_revoke.call_args.kwargs["expires_at"] is exp_dt


class TestLogoutViewOpaqueToken:
    """Opaque-token revocation path."""

    @pytest.mark.asyncio
    async def test_revokes_opaque_token(self) -> None:
        """Valid opaque token is marked inactive in the database."""
        view = LogoutView()
        req = _make_request(auth={"type": "token", "token": "raw-opaque-token"})
        with patch(
            "openviper.auth.views.logout.revoke_opaque_token", new_callable=AsyncMock
        ) as m_revoke:
            result = await view.post(req)
        m_revoke.assert_called_once_with("raw-opaque-token")
        assert result == {"detail": "Logged out."}

    @pytest.mark.asyncio
    async def test_skips_revocation_when_token_missing(self) -> None:
        """Missing raw token in auth_info skips revocation silently."""
        view = LogoutView()
        req = _make_request(auth={"type": "token", "token": ""})
        with patch(
            "openviper.auth.views.logout.revoke_opaque_token", new_callable=AsyncMock
        ) as m_revoke:
            result = await view.post(req)
        m_revoke.assert_not_called()
        assert result == {"detail": "Logged out."}


class TestLogoutViewSession:
    """Session revocation path."""

    @pytest.mark.asyncio
    async def test_calls_session_manager_logout(self) -> None:
        """Session logout delegates to SessionManager.logout."""
        view = LogoutView()
        req = _make_request(auth={"type": "session"})

        mock_manager = MagicMock()
        mock_manager.logout = AsyncMock()
        with patch("openviper.auth.views.logout.SessionManager", return_value=mock_manager):
            result = await view.post(req)

        mock_manager.logout.assert_called_once_with(req)
        assert result == {"detail": "Logged out."}


class TestLogoutViewUnknownAuthType:
    """Unrecognised auth type is silently accepted."""

    @pytest.mark.asyncio
    async def test_unknown_auth_type_returns_detail(self) -> None:
        """Unrecognised auth_type logs a warning and returns success."""
        view = LogoutView()
        req = _make_request(auth={"type": "custom_scheme"})
        result = await view.post(req)
        assert result == {"detail": "Logged out."}


# ---------------------------------------------------------------------------
# MeView
# ---------------------------------------------------------------------------


class TestMeView:
    """Tests for MeView.get."""

    @pytest.mark.asyncio
    async def test_raises_unauthorized_for_anonymous_user(self) -> None:
        """Anonymous (unauthenticated) request raises Unauthorized."""
        view = MeView()
        user = MagicMock()
        user.is_authenticated = False
        req = _make_request(user=user)
        with pytest.raises(Unauthorized):
            await view.get(req)

    @pytest.mark.asyncio
    async def test_raises_unauthorized_when_user_is_none(self) -> None:
        """Request with no user raises Unauthorized."""
        view = MeView()
        req = _make_request(user=None)
        with pytest.raises(Unauthorized):
            await view.get(req)

    @pytest.mark.asyncio
    async def test_returns_user_profile_dict(self) -> None:
        """Authenticated user profile is returned as a plain dict."""
        view = MeView()
        user = _make_user(pk=99, username="bob")
        user.email = "bob@example.com"
        user.first_name = "Bob"
        user.last_name = "Builder"
        user.is_active = True
        user.is_staff = True
        user.is_superuser = False

        req = _make_request(user=user)
        result = await view.get(req)

        assert result["id"] == 99
        assert result["username"] == "bob"
        assert result["email"] == "bob@example.com"
        assert result["first_name"] == "Bob"
        assert result["last_name"] == "Builder"
        assert result["is_active"] is True
        assert result["is_staff"] is True
        assert result["is_superuser"] is False

    @pytest.mark.asyncio
    async def test_handles_missing_optional_attributes(self) -> None:
        """Missing user attributes fall back to sensible defaults."""
        view = MeView()
        user = MagicMock(spec=[])
        user.is_authenticated = True
        req = _make_request(user=user)
        result = await view.get(req)
        assert result["id"] is None
        assert result["username"] is None


# ---------------------------------------------------------------------------
# Routes structure
# ---------------------------------------------------------------------------


class TestJwtRoutes:
    """jwt_routes list structure."""

    def test_has_two_entries(self) -> None:
        """jwt_routes contains exactly two route entries."""
        assert len(jwt_routes) == 2

    def test_login_path_and_methods(self) -> None:
        """First entry is the JWT login route."""
        path, _handler, methods = jwt_routes[0]
        assert path == "/jwt/login"
        assert methods == ["POST"]

    def test_logout_path_and_methods(self) -> None:
        """Second entry is the JWT logout route."""
        path, _handler, methods = jwt_routes[1]
        assert path == "/jwt/logout"
        assert methods == ["POST"]


class TestTokenRoutes:
    """token_routes list structure."""

    def test_has_two_entries(self) -> None:
        """token_routes contains exactly two route entries."""
        assert len(token_routes) == 2

    def test_login_path_and_methods(self) -> None:
        """First entry is the token login route."""
        path, _handler, methods = token_routes[0]
        assert path == "/token/login"
        assert methods == ["POST"]

    def test_logout_path_and_methods(self) -> None:
        """Second entry is the token logout route."""
        path, _handler, methods = token_routes[1]
        assert path == "/token/logout"
        assert methods == ["POST"]


class TestSessionRoutes:
    """session_routes list structure."""

    def test_has_two_entries(self) -> None:
        """session_routes contains exactly two route entries."""
        assert len(session_routes) == 2

    def test_login_path_and_methods(self) -> None:
        """First entry is the session login route."""
        path, _handler, methods = session_routes[0]
        assert path == "/session/login"
        assert methods == ["POST"]

    def test_logout_path_and_methods(self) -> None:
        """Second entry is the session logout route."""
        path, _handler, methods = session_routes[1]
        assert path == "/session/logout"
        assert methods == ["POST"]


class TestAllAuthRoutes:
    """all_auth_routes list structure."""

    def test_has_seven_entries(self) -> None:
        """all_auth_routes combines jwt, token, session routes plus /me."""
        assert len(all_auth_routes) == 7

    def test_me_route_is_last(self) -> None:
        """The /me route is the final entry in all_auth_routes."""
        path, _handler, methods = all_auth_routes[-1]
        assert path == "/me"
        assert methods == ["GET"]

    def test_all_entries_are_three_tuples(self) -> None:
        """Every route entry is a 3-tuple (path, handler, methods)."""
        for entry in all_auth_routes:
            assert len(entry) == 3
            path, _handler, methods = entry
            assert isinstance(path, str)
            assert isinstance(methods, list)

    def test_contains_all_jwt_routes(self) -> None:
        """All JWT routes are present in all_auth_routes."""
        all_paths = [path for path, _, _ in all_auth_routes]
        for path, _, _ in jwt_routes:
            assert path in all_paths

    def test_contains_all_token_routes(self) -> None:
        """All token routes are present in all_auth_routes."""
        all_paths = [path for path, _, _ in all_auth_routes]
        for path, _, _ in token_routes:
            assert path in all_paths

    def test_contains_all_session_routes(self) -> None:
        """All session routes are present in all_auth_routes."""
        all_paths = [path for path, _, _ in all_auth_routes]
        for path, _, _ in session_routes:
            assert path in all_paths


# ---------------------------------------------------------------------------
# Single-import check (openviper.auth)
# ---------------------------------------------------------------------------


class TestImportFromAuthPackage:
    """All new names are re-exported from openviper.auth."""

    def test_base_login_view_importable(self) -> None:
        """BaseLoginView is importable from openviper.auth."""
        assert auth_package.BaseLoginView is BaseLoginView

    def test_jwt_login_view_importable(self) -> None:
        """JWTLoginView is importable from openviper.auth."""
        assert auth_package.JWTLoginView is JWTLoginView

    def test_token_login_view_importable(self) -> None:
        """TokenLoginView is importable from openviper.auth."""
        assert auth_package.TokenLoginView is TokenLoginView

    def test_session_login_view_importable(self) -> None:
        """SessionLoginView is importable from openviper.auth."""
        assert auth_package.SessionLoginView is SessionLoginView

    def test_logout_view_importable(self) -> None:
        """LogoutView is importable from openviper.auth."""
        assert auth_package.LogoutView is LogoutView

    def test_me_view_importable(self) -> None:
        """MeView is importable from openviper.auth."""
        assert auth_package.MeView is MeView

    def test_jwt_routes_importable(self) -> None:
        """jwt_routes is importable from openviper.auth."""
        assert auth_package.jwt_routes is jwt_routes

    def test_token_routes_importable(self) -> None:
        """token_routes is importable from openviper.auth."""
        assert auth_package.token_routes is token_routes

    def test_session_routes_importable(self) -> None:
        """session_routes is importable from openviper.auth."""
        assert auth_package.session_routes is session_routes

    def test_all_auth_routes_importable(self) -> None:
        """all_auth_routes is importable from openviper.auth."""
        assert auth_package.all_auth_routes is all_auth_routes
