"""Unit tests for authentication lifecycle hooks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.exceptions import AuthHookConfigError, AuthHookExecutionError, AuthHookReject
from openviper.auth.hooks import (
    AuthHookContext,
    AuthHookRegistry,
    auth_hooks,
    register_auth_hook,
    safe_credentials,
)
from openviper.auth.views.jwt_login import JWTLoginView
from openviper.auth.views.logout import LogoutView
from openviper.exceptions import Unauthorized


@pytest.fixture(autouse=True)
def clear_global_auth_hooks() -> None:
    auth_hooks.clear()
    yield
    auth_hooks.clear()


def make_request(body: dict[str, object] | None = None) -> MagicMock:
    request = MagicMock()
    request.json = AsyncMock(return_value=body or {})
    request.cookies = {}
    request.headers = {"user-agent": "pytest"}
    request.client = MagicMock(host="127.0.0.1")
    request.auth = {"type": "none"}
    request._scope = {}
    request._session = None
    return request


def make_user() -> MagicMock:
    user = MagicMock()
    user.pk = 7
    user.is_active = True
    user.is_authenticated = True
    return user


class TestAuthHookRegistry:
    @pytest.mark.asyncio
    async def test_registers_and_runs_hooks_in_order(self) -> None:
        registry = AuthHookRegistry()
        calls: list[str] = []

        @registry.before_login
        def first(context: AuthHookContext) -> None:
            calls.append("first")

        @registry.before_login
        async def second(context: AuthHookContext) -> None:
            calls.append("second")

        await registry.run_before_login(AuthHookContext())

        assert calls == ["first", "second"]

    def test_invalid_hook_name_raises_config_error(self) -> None:
        with pytest.raises(AuthHookConfigError):
            register_auth_hook("unknown", lambda context: None)

    def test_non_callable_hook_raises_config_error(self) -> None:
        registry = AuthHookRegistry()
        with pytest.raises(AuthHookConfigError):
            registry.register("before_login", "not-callable")

    def test_explicit_non_callable_hook_raises_config_error(self) -> None:
        with pytest.raises(AuthHookConfigError):
            register_auth_hook("before_login", "not-callable")


class TestSafeCredentials:
    def test_sensitive_credential_fields_are_stripped(self) -> None:
        safe = safe_credentials(
            {
                "email": "user@example.com",
                "password": "secret",
                "otp": "123456",
                "refresh_token": "raw-refresh",
                "tenant": "acme",
            }
        )

        assert safe == {"email": "user@example.com", "tenant": "acme"}


class TestLoginIntegration:
    @pytest.mark.asyncio
    async def test_login_flow_calls_before_login_and_on_login(self) -> None:
        user = make_user()
        request = make_request({"username": "alice", "password": "secret"})
        calls: list[str] = []

        @auth_hooks.before_login
        def before_login(context: AuthHookContext) -> None:
            calls.append("before")
            assert context.credentials == {"username": "alice"}

        @auth_hooks.on_login
        async def on_login(context: AuthHookContext) -> None:
            calls.append("after")
            assert context.token == {"type": "jwt", "issued": True}

        with (
            patch(
                "openviper.auth.views.base_login.authenticate",
                new_callable=AsyncMock,
                return_value=user,
            ),
            patch("openviper.auth.views.jwt_login.create_access_token", return_value="access"),
            patch("openviper.auth.views.jwt_login.create_refresh_token", return_value="refresh"),
        ):
            result = await JWTLoginView().post(request)

        assert calls == ["before", "after"]
        assert result == {"access": "access", "refresh": "refresh"}

    @pytest.mark.asyncio
    async def test_before_login_rejection_prevents_on_login(self) -> None:
        user = make_user()
        request = make_request({"username": "alice", "password": "secret"})
        on_login = AsyncMock()

        @auth_hooks.before_login
        def before_login(context: AuthHookContext) -> None:
            raise AuthHookReject("Denied.")

        auth_hooks.on_login(on_login)

        with (
            patch(
                "openviper.auth.views.base_login.authenticate",
                new_callable=AsyncMock,
                return_value=user,
            ),
            patch("openviper.auth.views.jwt_login.create_access_token") as create_access,
            pytest.raises(Unauthorized, match="Denied"),
        ):
            await JWTLoginView().post(request)

        create_access.assert_not_called()
        on_login.assert_not_called()

    @pytest.mark.asyncio
    async def test_unexpected_before_login_error_fails_closed(self) -> None:
        user = make_user()
        request = make_request({"username": "alice", "password": "secret"})

        @auth_hooks.before_login
        def before_login(context: AuthHookContext) -> None:
            raise RuntimeError("database down")

        with (
            patch(
                "openviper.auth.views.base_login.authenticate",
                new_callable=AsyncMock,
                return_value=user,
            ),
            pytest.raises(Unauthorized, match="Login rejected"),
        ):
            await JWTLoginView().post(request)

    @pytest.mark.asyncio
    async def test_on_login_error_logs_and_continues_by_default(self) -> None:
        user = make_user()
        request = make_request({"username": "alice", "password": "secret"})

        @auth_hooks.on_login
        def on_login(context: AuthHookContext) -> None:
            raise RuntimeError("audit unavailable")

        with (
            patch(
                "openviper.auth.views.base_login.authenticate",
                new_callable=AsyncMock,
                return_value=user,
            ),
            patch("openviper.auth.views.jwt_login.create_access_token", return_value="access"),
            patch("openviper.auth.views.jwt_login.create_refresh_token", return_value="refresh"),
        ):
            result = await JWTLoginView().post(request)

        assert result == {"access": "access", "refresh": "refresh"}

    @pytest.mark.asyncio
    async def test_on_login_error_raises_in_strict_mode(self) -> None:
        user = make_user()
        request = make_request({"username": "alice", "password": "secret"})

        @auth_hooks.on_login
        def on_login(context: AuthHookContext) -> None:
            raise RuntimeError("audit unavailable")

        with (
            patch("openviper.auth.hooks.settings") as hook_settings,
            patch(
                "openviper.auth.views.base_login.authenticate",
                new_callable=AsyncMock,
                return_value=user,
            ),
            patch("openviper.auth.views.jwt_login.create_access_token", return_value="access"),
            patch("openviper.auth.views.jwt_login.create_refresh_token", return_value="refresh"),
        ):
            hook_settings.AUTH_HOOKS = {"on_login_error": "raise"}
            with pytest.raises(AuthHookExecutionError):
                await JWTLoginView().post(request)


class TestLogoutIntegration:
    @pytest.mark.asyncio
    async def test_logout_flow_calls_on_logout(self) -> None:
        request = make_request()
        request.auth = {"type": "token", "token": "raw-token"}
        request.user = make_user()
        seen: list[object | None] = []

        @auth_hooks.on_logout
        async def on_logout(context: AuthHookContext) -> None:
            seen.append(context.user)
            assert context.token == {"type": "token", "present": True}

        with patch(
            "openviper.auth.views.logout.revoke_opaque_token",
            new_callable=AsyncMock,
        ):
            result = await LogoutView().post(request)

        assert seen == [request.user]
        assert result == {"detail": "Logged out."}

    @pytest.mark.asyncio
    async def test_on_logout_error_logs_and_continues_by_default(self) -> None:
        request = make_request()
        request.auth = {"type": "token", "token": "raw-token"}

        @auth_hooks.on_logout
        def on_logout(context: AuthHookContext) -> None:
            raise RuntimeError("audit unavailable")

        with patch(
            "openviper.auth.views.logout.revoke_opaque_token",
            new_callable=AsyncMock,
        ):
            result = await LogoutView().post(request)

        assert result == {"detail": "Logged out."}

    @pytest.mark.asyncio
    async def test_on_logout_error_raises_in_strict_mode(self) -> None:
        request = make_request()
        request.auth = {"type": "token", "token": "raw-token"}

        @auth_hooks.on_logout
        def on_logout(context: AuthHookContext) -> None:
            raise RuntimeError("audit unavailable")

        with (
            patch("openviper.auth.hooks.settings") as hook_settings,
            patch(
                "openviper.auth.views.logout.revoke_opaque_token",
                new_callable=AsyncMock,
            ),
        ):
            hook_settings.AUTH_HOOKS = {"on_logout_error": "raise"}
            with pytest.raises(AuthHookExecutionError):
                await LogoutView().post(request)
