"""Comprehensive unit tests for openviper/admin/api/views.py."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.admin.api.views import (
    _is_auth_user_model,
    _serialize_instance_with_children,
    get_admin_router,
)
from openviper.exceptions import NotFound, PermissionDenied, Unauthorized, ValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_handler(router, name: str):
    """Find a handler by function name in the router's route list."""
    for route in router.routes:
        if route.handler.__name__ == name:
            return route.handler
    return None


def _mock_request(json_data=None, query_params=None, user=None):
    """Build a minimal mock Request."""
    req = MagicMock(name="request")
    req.json = AsyncMock(return_value=json_data or {})
    req.query_params = query_params or {}
    if user is None:
        user = MagicMock()
        user.id = 1
        user.username = "admin"
        user.email = "admin@example.com"
        user.is_staff = True
        user.is_superuser = True
    req.user = user
    return req


def _make_router():
    """Get the admin API router."""
    return get_admin_router()


# ---------------------------------------------------------------------------
# _is_auth_user_model
# ---------------------------------------------------------------------------


class TestIsAuthUserModel:
    def test_user_model_returns_true(self):
        from openviper.auth import get_user_model

        User = get_user_model()
        assert _is_auth_user_model(User) is True

    def test_non_user_model_returns_false(self):
        class SomeOtherClass:
            pass

        assert _is_auth_user_model(SomeOtherClass) is False

    def test_exception_returns_false(self):
        """When issubclass raises, return False."""

        class Broken:
            pass

        # Pass something that will fail issubclass check
        with patch("openviper.admin.api.views.issubclass", side_effect=TypeError):
            result = _is_auth_user_model(Broken)
        assert result is False


# ---------------------------------------------------------------------------
# _serialize_instance_with_children
# ---------------------------------------------------------------------------


class TestSerializeInstanceWithChildren:
    @pytest.mark.asyncio
    async def test_basic_serialization(self):
        model_admin = MagicMock()
        model_admin.child_tables = []
        model_admin.inlines = []

        model_class = MagicMock()
        model_class._fields = {"name": MagicMock(), "age": MagicMock()}
        model_class.__name__ = "TestModel"

        instance = MagicMock()
        instance.id = 1
        instance.name = "Alice"
        instance.age = 30

        request = _mock_request()
        result = await _serialize_instance_with_children(
            request, model_admin, model_class, instance
        )

        assert result["id"] == 1
        assert result["name"] == "Alice"
        assert result["age"] == 30

    @pytest.mark.asyncio
    async def test_datetime_serialized_to_isoformat(self):
        from datetime import datetime

        model_admin = MagicMock()
        model_admin.child_tables = []
        model_admin.inlines = []

        model_class = MagicMock()
        dt = datetime(2024, 1, 15, 12, 0, 0)
        model_class._fields = {"created_at": MagicMock()}
        model_class.__name__ = "TestModel"

        instance = MagicMock()
        instance.id = 2
        instance.created_at = dt

        request = _mock_request()
        result = await _serialize_instance_with_children(
            request, model_admin, model_class, instance
        )

        assert result["created_at"] == dt.isoformat()

    @pytest.mark.asyncio
    async def test_password_excluded_for_user_model(self):
        model_admin = MagicMock()
        model_admin.child_tables = []
        model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {"username": MagicMock(), "password": MagicMock()}
        mock_model.__name__ = "User"

        instance = MagicMock()
        instance.id = 1
        instance.username = "admin"
        instance.password = "secret_hash"

        # Patch _is_auth_user_model to return True so password is excluded
        with patch("openviper.admin.api.views._is_auth_user_model", return_value=True):
            result = await _serialize_instance_with_children(
                _mock_request(), model_admin, mock_model, instance
            )

        assert "password" not in result
        assert result["username"] == "admin"

    @pytest.mark.asyncio
    async def test_non_serializable_value_converted_to_str(self):
        model_admin = MagicMock()
        model_admin.child_tables = []
        model_admin.inlines = []

        model_class = MagicMock()

        # Use an object that's not str/int/float/bool/list/dict
        class CustomObj:
            def __str__(self):
                return "custom_value"

        custom = CustomObj()
        model_class._fields = {"data": MagicMock()}
        model_class.__name__ = "TestModel"

        instance = MagicMock()
        instance.id = 3
        instance.data = custom

        result = await _serialize_instance_with_children(
            _mock_request(), model_admin, model_class, instance
        )
        assert result["data"] == "custom_value"


# ---------------------------------------------------------------------------
# admin_config endpoint
# ---------------------------------------------------------------------------


class TestAdminConfig:
    @pytest.mark.asyncio
    async def test_returns_config(self):
        router = _make_router()
        handler = _get_handler(router, "admin_config")
        assert handler is not None

        with patch("openviper.admin.api.views.settings") as ms:
            ms.ADMIN_TITLE = "My Admin"
            ms.ADMIN_HEADER_TITLE = "My Header"
            ms.ADMIN_FOOTER_TITLE = "My Footer"
            ms.USER_MODEL = None
            ms.AUTH_USER_MODEL = None
            response = await handler(_mock_request())

        body = json.loads(response.body)
        assert "admin_title" in body
        assert "user_model" in body

    @pytest.mark.asyncio
    async def test_defaults_when_settings_missing(self):
        router = _make_router()
        handler = _get_handler(router, "admin_config")

        with patch("openviper.admin.api.views.settings") as ms:
            del ms.ADMIN_TITLE
            ms.USER_MODEL = None
            ms.AUTH_USER_MODEL = None
            # Use spec to make getattr(settings, "ADMIN_TITLE", ...) return default
            type(ms).__getattr__ = lambda s, k: (_ for _ in ()).throw(AttributeError(k))
            response = await handler(_mock_request())

        body = json.loads(response.body)
        assert body.get("admin_title") == "OpenViper Admin"


# ---------------------------------------------------------------------------
# admin_login endpoint
# ---------------------------------------------------------------------------


class TestAdminLogin:
    @pytest.mark.asyncio
    async def test_missing_credentials_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "admin_login")

        req = _mock_request(json_data={"username": "", "password": ""})
        with pytest.raises(ValidationError):
            await handler(req)

    @pytest.mark.asyncio
    async def test_missing_password_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "admin_login")

        req = _mock_request(json_data={"username": "admin"})
        with pytest.raises(ValidationError):
            await handler(req)

    @pytest.mark.asyncio
    async def test_invalid_credentials_raises_unauthorized(self):
        router = _make_router()
        handler = _get_handler(router, "admin_login")

        req = _mock_request(json_data={"username": "wrong", "password": "bad"})
        with (
            patch(
                "openviper.admin.api.views.authenticate",
                new_callable=AsyncMock,
                side_effect=Exception("Invalid credentials"),
            ),
            pytest.raises(Unauthorized),
        ):
            await handler(req)

    @pytest.mark.asyncio
    async def test_non_staff_user_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "admin_login")

        req = _mock_request(json_data={"username": "user", "password": "pass"})
        mock_user = MagicMock()
        mock_user.is_staff = False
        mock_user.is_superuser = False
        mock_user.id = 5
        mock_user.username = "user"

        with (
            patch(
                "openviper.admin.api.views.authenticate",
                new_callable=AsyncMock,
                return_value=mock_user,
            ),
            pytest.raises(PermissionDenied),
        ):
            await handler(req)

    @pytest.mark.asyncio
    async def test_valid_login_returns_tokens(self):
        router = _make_router()
        handler = _get_handler(router, "admin_login")

        req = _mock_request(json_data={"username": "admin", "password": "pass"})
        mock_user = MagicMock()
        mock_user.is_staff = True
        mock_user.is_superuser = False
        mock_user.id = 1
        mock_user.username = "admin"
        mock_user.email = "admin@example.com"

        with (
            patch(
                "openviper.admin.api.views.authenticate",
                new_callable=AsyncMock,
                return_value=mock_user,
            ),
            patch("openviper.admin.api.views.create_access_token", return_value="access_tok"),
            patch("openviper.admin.api.views.create_refresh_token", return_value="refresh_tok"),
        ):
            response = await handler(req)

        body = json.loads(response.body)
        assert body["access_token"] == "access_tok"
        assert body["refresh_token"] == "refresh_tok"
        assert body["user"]["username"] == "admin"


# ---------------------------------------------------------------------------
# admin_logout endpoint
# ---------------------------------------------------------------------------


class TestAdminLogout:
    @pytest.mark.asyncio
    async def test_logout_returns_success(self):
        router = _make_router()
        handler = _get_handler(router, "admin_logout")

        response = await handler(_mock_request())
        body = json.loads(response.body)
        assert "detail" in body
        assert "logged out" in body["detail"].lower()

    @pytest.mark.asyncio
    async def test_logout_json_parse_exception_is_suppressed(self):
        """Lines 248-249: request.json() raising an exception is caught silently."""
        router = _make_router()
        handler = _get_handler(router, "admin_logout")

        req = _mock_request()
        req.json = AsyncMock(side_effect=Exception("malformed JSON"))

        # Must not raise — refresh_token falls back to None
        response = await handler(req)
        body = json.loads(response.body)
        assert "logged out" in body["detail"].lower()


# ---------------------------------------------------------------------------
# admin_refresh_token endpoint
# ---------------------------------------------------------------------------


class TestAdminRefreshToken:
    @pytest.mark.asyncio
    async def test_missing_refresh_token_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "admin_refresh_token")

        req = _mock_request(json_data={})
        with pytest.raises(ValidationError):
            await handler(req)

    @pytest.mark.asyncio
    async def test_invalid_token_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "admin_refresh_token")

        req = _mock_request(json_data={"refresh_token": "bad_token"})
        with (
            patch(
                "openviper.admin.api.views.decode_refresh_token",
                side_effect=Exception("invalid"),
            ),
            pytest.raises(ValidationError),
        ):
            await handler(req)

    @pytest.mark.asyncio
    async def test_user_not_found_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "admin_refresh_token")

        mock_User = MagicMock()
        mock_User.objects.get_or_none = AsyncMock(return_value=None)

        req = _mock_request(json_data={"refresh_token": "valid_tok"})
        with (
            patch("openviper.admin.api.views.decode_refresh_token", return_value={"sub": 99}),
            patch("openviper.admin.api.views.User", mock_User),
            pytest.raises(ValidationError, match="User not found"),
        ):
            await handler(req)

    @pytest.mark.asyncio
    async def test_valid_refresh_returns_access_token(self):
        router = _make_router()
        handler = _get_handler(router, "admin_refresh_token")

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "admin"
        mock_User = MagicMock()
        mock_User.objects.get_or_none = AsyncMock(return_value=mock_user)

        req = _mock_request(json_data={"refresh_token": "valid_tok"})
        with (
            patch("openviper.admin.api.views.decode_refresh_token", return_value={"sub": 1}),
            patch("openviper.admin.api.views.User", mock_User),
            patch("openviper.admin.api.views.create_access_token", return_value="new_access"),
        ):
            response = await handler(req)

        body = json.loads(response.body)
        assert body["access_token"] == "new_access"


# ---------------------------------------------------------------------------
# admin_current_user endpoint
# ---------------------------------------------------------------------------


class TestAdminCurrentUser:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "admin_current_user")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request())

    @pytest.mark.asyncio
    async def test_returns_user_info(self):
        router = _make_router()
        handler = _get_handler(router, "admin_current_user")

        user = MagicMock()
        user.id = 42
        user.username = "superadmin"
        user.email = "super@example.com"
        user.is_staff = True
        user.is_superuser = True

        req = _mock_request(user=user)
        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            response = await handler(req)

        body = json.loads(response.body)
        assert body["id"] == 42
        assert body["username"] == "superadmin"
        assert body["is_staff"] is True


# ---------------------------------------------------------------------------
# admin_change_password endpoint
# ---------------------------------------------------------------------------


class TestAdminChangePassword:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "admin_change_password")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request())

    @pytest.mark.asyncio
    async def test_missing_current_password_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "admin_change_password")

        req = _mock_request(json_data={"new_password": "newpass123"})
        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=True),
            pytest.raises(ValidationError),
        ):
            await handler(req)

    @pytest.mark.asyncio
    async def test_password_mismatch_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "admin_change_password")

        req = _mock_request(
            json_data={
                "current_password": "oldpass",
                "new_password": "newpass123",
                "confirm_password": "different",
            }
        )
        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=True),
            pytest.raises(ValidationError, match="do not match"),
        ):
            await handler(req)

    @pytest.mark.asyncio
    async def test_short_password_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "admin_change_password")

        req = _mock_request(
            json_data={
                "current_password": "oldpass",
                "new_password": "short",
                "confirm_password": "short",
            }
        )
        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=True),
            pytest.raises(ValidationError, match="8 characters"),
        ):
            await handler(req)

    @pytest.mark.asyncio
    async def test_user_not_found_raises_not_found(self):
        router = _make_router()
        handler = _get_handler(router, "admin_change_password")

        mock_User = MagicMock()
        mock_User.objects.get_or_none = AsyncMock(return_value=None)

        req = _mock_request(
            json_data={
                "current_password": "oldpass123",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            }
        )
        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=True),
            patch("openviper.admin.api.views.User", mock_User),
            pytest.raises(NotFound),
        ):
            await handler(req)

    @pytest.mark.asyncio
    async def test_wrong_current_password_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "admin_change_password")

        mock_user = MagicMock()
        mock_user.check_password.return_value = False
        mock_User = MagicMock()
        mock_User.objects.get_or_none = AsyncMock(return_value=mock_user)

        req = _mock_request(
            json_data={
                "current_password": "wrongpass",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            }
        )
        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=True),
            patch("openviper.admin.api.views.User", mock_User),
            pytest.raises(ValidationError, match="incorrect"),
        ):
            await handler(req)

    @pytest.mark.asyncio
    async def test_successful_password_change(self):
        router = _make_router()
        handler = _get_handler(router, "admin_change_password")

        mock_user = MagicMock()
        mock_user.check_password.return_value = True
        mock_user.save = AsyncMock()
        mock_User = MagicMock()
        mock_User.objects.get_or_none = AsyncMock(return_value=mock_user)

        req = _mock_request(
            json_data={
                "current_password": "correctpass",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            }
        )
        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=True),
            patch("openviper.admin.api.views.User", mock_User),
        ):
            response = await handler(req)

        body = json.loads(response.body)
        assert "password changed" in body["detail"].lower()
        mock_user.set_password.assert_called_once_with("newpass123")
        mock_user.save.assert_awaited_once()


# ---------------------------------------------------------------------------
# admin_change_user_password endpoint
# ---------------------------------------------------------------------------


class TestAdminChangeUserPassword:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "admin_change_user_password")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request(), user_id=1)

    @pytest.mark.asyncio
    async def test_non_superuser_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "admin_change_user_password")

        user = MagicMock()
        user.is_superuser = False
        req = _mock_request(user=user)
        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=True),
            pytest.raises(PermissionDenied, match="superuser"),
        ):
            await handler(req, user_id=1)

    @pytest.mark.asyncio
    async def test_target_user_not_found_raises_not_found(self):
        router = _make_router()
        handler = _get_handler(router, "admin_change_user_password")

        mock_User = MagicMock()
        mock_User.objects.get_or_none = AsyncMock(return_value=None)

        req = _mock_request(
            json_data={"new_password": "newpass123", "confirm_password": "newpass123"}
        )
        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=True),
            patch("openviper.admin.api.views.User", mock_User),
            pytest.raises(NotFound),
        ):
            await handler(req, user_id=999)

    @pytest.mark.asyncio
    async def test_successful_user_password_change(self):
        router = _make_router()
        handler = _get_handler(router, "admin_change_user_password")

        target_user = MagicMock()
        target_user.username = "targetuser"
        target_user.save = AsyncMock()
        mock_User = MagicMock()
        mock_User.objects.get_or_none = AsyncMock(return_value=target_user)

        req = _mock_request(
            json_data={"new_password": "newpass123", "confirm_password": "newpass123"}
        )
        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=True),
            patch("openviper.admin.api.views.User", mock_User),
        ):
            response = await handler(req, user_id=5)

        body = json.loads(response.body)
        assert "targetuser" in body["detail"]
        target_user.set_password.assert_called_once_with("newpass123")


# ---------------------------------------------------------------------------
# admin_dashboard endpoint
# ---------------------------------------------------------------------------


class TestAdminDashboard:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "admin_dashboard")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request())

    @pytest.mark.asyncio
    async def test_returns_stats_and_activity(self):
        router = _make_router()
        handler = _get_handler(router, "admin_dashboard")

        mock_model = MagicMock()
        mock_model.__name__ = "Article"
        mock_model.objects.count = AsyncMock(return_value=5)
        mock_admin_obj = MagicMock()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_all_models",
                return_value=[(mock_model, mock_admin_obj)],
            ):
                with patch(
                    "openviper.admin.api.views.get_recent_activity",
                    new_callable=AsyncMock,
                    return_value=[],
                ):
                    response = await handler(_mock_request())

        body = json.loads(response.body)
        assert "stats" in body
        assert "recent_activity" in body
        assert body["stats"]["Article"] == 5

    @pytest.mark.asyncio
    async def test_activity_exception_is_swallowed(self):
        """If get_recent_activity raises, the dashboard still returns successfully."""
        router = _make_router()
        handler = _get_handler(router, "admin_dashboard")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=True),
            patch("openviper.admin.api.views.admin.get_all_models", return_value=[]),
            patch(
                "openviper.admin.api.views.get_recent_activity",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB down"),
            ),
        ):
            response = await handler(_mock_request())

        body = json.loads(response.body)
        assert body["recent_activity"] == []


# ---------------------------------------------------------------------------
# list_models endpoint
# ---------------------------------------------------------------------------


class TestListModels:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "list_models")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request())

    @pytest.mark.asyncio
    async def test_returns_models_list(self):
        router = _make_router()
        handler = _get_handler(router, "list_models")

        mock_model = MagicMock()
        mock_model.__name__ = "Article"
        mock_admin_obj = MagicMock()
        mock_admin_obj.get_model_info.return_value = {"name": "Article"}

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=True),
            patch("openviper.admin.api.views.check_model_permission", return_value=True),
            patch(
                "openviper.admin.api.views.admin.get_all_models",
                return_value=[(mock_model, mock_admin_obj)],
            ),
            patch(
                "openviper.admin.api.views.admin.get_models_grouped_by_app",
                return_value={"myapp": [(mock_model, mock_admin_obj)]},
            ),
        ):
            response = await handler(_mock_request())

        body = json.loads(response.body)
        assert "models" in body
        assert "apps" in body


# ---------------------------------------------------------------------------
# get_model_config endpoint
# ---------------------------------------------------------------------------


class TestGetModelConfig:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "get_model_config")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request(), app_label="myapp", model_name="Article")

    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "get_model_config")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                side_effect=NotRegistered("not found"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), app_label="x", model_name="y")

    @pytest.mark.asyncio
    async def test_no_view_permission_raises_permission_denied(self):

        router = _make_router()
        handler = _get_handler(router, "get_model_config")

        mock_model_admin = MagicMock()
        mock_model = MagicMock()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=False
                    ):
                        with pytest.raises(PermissionDenied):
                            await handler(_mock_request(), app_label="myapp", model_name="Article")

    @pytest.mark.asyncio
    async def test_returns_model_info(self):
        router = _make_router()
        handler = _get_handler(router, "get_model_config")

        mock_model_admin = MagicMock()
        mock_model_admin.get_model_info.return_value = {"name": "Article", "fields": []}
        mock_model = MagicMock()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(
                            _mock_request(), app_label="myapp", model_name="Article"
                        )

        body = json.loads(response.body)
        assert body["name"] == "Article"


# ---------------------------------------------------------------------------
# list_instances_by_app endpoint
# ---------------------------------------------------------------------------


def _make_qs(items=None, total=0):
    """Build a mock QuerySet."""
    qs = MagicMock()
    qs.filter.return_value = qs
    qs.order_by.return_value = qs
    qs.offset.return_value = qs
    qs.limit.return_value = qs
    qs.count = AsyncMock(return_value=total)
    qs.all = AsyncMock(return_value=items or [])
    return qs


class TestListInstancesByApp:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "list_instances_by_app")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request(), app_label="myapp", model_name="Article")

    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "list_instances_by_app")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                side_effect=NotRegistered("not found"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), app_label="x", model_name="y")

    @pytest.mark.asyncio
    async def test_no_view_permission_returns_empty_result(self):
        router = _make_router()
        handler = _get_handler(router, "list_instances_by_app")

        mock_model_admin = MagicMock()
        mock_model_admin.list_per_page = 20
        mock_model_admin.get_list_display.return_value = ["name"]
        mock_model = MagicMock()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=False
                    ):
                        response = await handler(
                            _mock_request(), app_label="myapp", model_name="Article"
                        )

        body = json.loads(response.body)
        assert body["items"] == []
        assert body["total"] == 0
        assert body["permission_denied"] is True

    @pytest.mark.asyncio
    async def test_returns_paginated_results(self):
        router = _make_router()
        handler = _get_handler(router, "list_instances_by_app")

        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.name = "Test Article"

        mock_model_admin = MagicMock()
        mock_model_admin.list_per_page = 20
        mock_model_admin.get_list_display.return_value = ["name"]
        mock_model_admin.get_search_fields.return_value = []
        mock_model_admin.get_ordering.return_value = []

        qs = _make_qs(items=[mock_instance], total=1)
        mock_model = MagicMock()
        mock_model.objects.all.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(
                            _mock_request(query_params={"page": "1", "per_page": "20"}),
                            app_label="myapp",
                            model_name="Article",
                        )

        body = json.loads(response.body)
        assert body["total"] == 1
        assert len(body["items"]) == 1

    @pytest.mark.asyncio
    async def test_search_query_applied(self):
        router = _make_router()
        handler = _get_handler(router, "list_instances_by_app")

        mock_model_admin = MagicMock()
        mock_model_admin.list_per_page = 20
        mock_model_admin.get_list_display.return_value = ["name"]
        mock_model_admin.get_search_fields.return_value = ["name"]
        mock_model_admin.get_ordering.return_value = []

        qs = _make_qs(items=[], total=0)
        mock_model = MagicMock()
        mock_model.objects.all.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(
                            _mock_request(query_params={"search": "test"}),
                            app_label="myapp",
                            model_name="Article",
                        )

        body = json.loads(response.body)
        assert "items" in body


# ---------------------------------------------------------------------------
# create_instance_by_app endpoint
# ---------------------------------------------------------------------------


class TestCreateInstanceByApp:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "create_instance_by_app")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request(), app_label="myapp", model_name="Article")

    @pytest.mark.asyncio
    async def test_no_add_permission_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "create_instance_by_app")

        mock_model_admin = MagicMock()
        mock_model_admin.has_add_permission.return_value = False
        mock_model = MagicMock()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with pytest.raises(PermissionDenied):
                        await handler(_mock_request(), app_label="myapp", model_name="Article")

    @pytest.mark.asyncio
    async def test_successful_create_returns_201(self):
        router = _make_router()
        handler = _get_handler(router, "create_instance_by_app")

        mock_instance = MagicMock()
        mock_instance.id = 99
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_add_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.child_tables = []
        mock_model_admin.inlines = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.return_value = mock_instance

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

        req = _mock_request(json_data={"title": "New Article"})
        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.get_engine",
                        new_callable=AsyncMock,
                        return_value=mock_engine,
                    ):
                        with patch(
                            "openviper.admin.api.views._serialize_instance_with_children",
                            new_callable=AsyncMock,
                            return_value={"id": 99, "title": "New Article"},
                        ):
                            response = await handler(req, app_label="myapp", model_name="Article")

        assert response.status_code == 201


# ---------------------------------------------------------------------------
# get_instance_by_app endpoint
# ---------------------------------------------------------------------------


class TestGetInstanceByApp:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "get_instance_by_app")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request(), app_label="myapp", model_name="Article", obj_id=1)

    @pytest.mark.asyncio
    async def test_instance_not_found_raises_not_found(self):
        router = _make_router()
        handler = _get_handler(router, "get_instance_by_app")

        mock_model_admin = MagicMock()
        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=None)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with pytest.raises(NotFound):
                        await handler(
                            _mock_request(), app_label="myapp", model_name="Article", obj_id=999
                        )

    @pytest.mark.asyncio
    async def test_successful_retrieval(self):
        router = _make_router()
        handler = _get_handler(router, "get_instance_by_app")

        mock_instance = MagicMock()
        mock_instance.id = 1

        mock_model_admin = MagicMock()
        mock_model_admin.has_view_permission.return_value = True
        mock_model_admin.get_model_info.return_value = {"name": "Article"}
        mock_model_admin.get_readonly_fields.return_value = []
        mock_model_admin.get_fieldsets.return_value = []
        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views._serialize_instance_with_children",
                        new_callable=AsyncMock,
                        return_value={"id": 1},
                    ):
                        response = await handler(
                            _mock_request(), app_label="myapp", model_name="Article", obj_id=1
                        )

        body = json.loads(response.body)
        assert "instance" in body
        assert "model_info" in body


# ---------------------------------------------------------------------------
# delete_instance_by_app endpoint
# ---------------------------------------------------------------------------


class TestDeleteInstanceByApp:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "delete_instance_by_app")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request(), app_label="myapp", model_name="Article", obj_id=1)

    @pytest.mark.asyncio
    async def test_instance_not_found_raises_not_found(self):
        router = _make_router()
        handler = _get_handler(router, "delete_instance_by_app")

        mock_model_admin = MagicMock()
        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=None)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with pytest.raises(NotFound):
                        await handler(
                            _mock_request(), app_label="myapp", model_name="Article", obj_id=999
                        )

    @pytest.mark.asyncio
    async def test_no_delete_permission_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "delete_instance_by_app")

        mock_instance = MagicMock()
        mock_model_admin = MagicMock()
        mock_model_admin.has_delete_permission.return_value = False
        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with pytest.raises(PermissionDenied):
                        await handler(
                            _mock_request(), app_label="myapp", model_name="Article", obj_id=1
                        )

    @pytest.mark.asyncio
    async def test_successful_delete_returns_detail(self):
        router = _make_router()
        handler = _get_handler(router, "delete_instance_by_app")

        mock_instance = MagicMock()
        mock_instance.delete = AsyncMock()
        mock_model_admin = MagicMock()
        mock_model_admin.has_delete_permission.return_value = True
        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch("openviper.admin.api.views.log_change", new_callable=AsyncMock):
                        response = await handler(
                            _mock_request(), app_label="myapp", model_name="Article", obj_id=1
                        )

        body = json.loads(response.body)
        assert "deleted" in body["detail"].lower()
        mock_instance.delete.assert_awaited_once()


# ---------------------------------------------------------------------------
# bulk_action_by_app endpoint
# ---------------------------------------------------------------------------


class TestBulkActionByApp:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "bulk_action_by_app")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request(), app_label="myapp", model_name="Article")

    @pytest.mark.asyncio
    async def test_missing_action_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "bulk_action_by_app")

        mock_model = MagicMock()
        mock_model_admin = MagicMock()

        req = _mock_request(json_data={"ids": [1, 2, 3]})
        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with pytest.raises(ValidationError):
                        await handler(req, app_label="myapp", model_name="Article")

    @pytest.mark.asyncio
    async def test_missing_ids_raises_validation_error(self):
        router = _make_router()
        handler = _get_handler(router, "bulk_action_by_app")

        mock_model = MagicMock()
        mock_model_admin = MagicMock()

        req = _mock_request(json_data={"action": "delete"})
        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with pytest.raises(ValidationError):
                        await handler(req, app_label="myapp", model_name="Article")

    @pytest.mark.asyncio
    async def test_action_not_found_raises_not_found(self):
        router = _make_router()
        handler = _get_handler(router, "bulk_action_by_app")

        mock_model = MagicMock()
        mock_model_admin = MagicMock()
        qs = _make_qs()
        mock_model.objects.filter.return_value = qs

        req = _mock_request(json_data={"action": "nonexistent", "ids": [1]})
        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with (
                        patch("openviper.admin.api.views.get_action", return_value=None),
                        pytest.raises(NotFound),
                    ):
                        await handler(req, app_label="myapp", model_name="Article")

    @pytest.mark.asyncio
    async def test_successful_bulk_action(self):
        router = _make_router()
        handler = _get_handler(router, "bulk_action_by_app")

        mock_model = MagicMock()
        mock_model_admin = MagicMock()
        qs = _make_qs()
        mock_model.objects.filter.return_value = qs

        action_result = MagicMock()
        action_result.success = True
        action_result.count = 2
        action_result.message = "Deleted 2 items."
        action_result.errors = []

        mock_action = MagicMock()
        mock_action.has_permission.return_value = True
        mock_action.execute = AsyncMock(return_value=action_result)

        req = _mock_request(json_data={"action": "delete_selected", "ids": [1, 2]})
        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch("openviper.admin.api.views.get_action", return_value=mock_action):
                        response = await handler(req, app_label="myapp", model_name="Article")

        body = json.loads(response.body)
        assert body["success"] is True
        assert body["count"] == 2


# ---------------------------------------------------------------------------
# get_instance_history_by_app endpoint
# ---------------------------------------------------------------------------


class TestGetInstanceHistoryByApp:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "get_instance_history_by_app")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request(), app_label="myapp", model_name="Article", obj_id=1)

    @pytest.mark.asyncio
    async def test_instance_not_found_raises_not_found(self):
        router = _make_router()
        handler = _get_handler(router, "get_instance_history_by_app")

        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=None)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_by_app_and_name",
                return_value=mock_model,
            ):
                with pytest.raises(NotFound):
                    await handler(
                        _mock_request(), app_label="myapp", model_name="Article", obj_id=999
                    )

    @pytest.mark.asyncio
    async def test_returns_history(self):
        router = _make_router()
        handler = _get_handler(router, "get_instance_history_by_app")

        from datetime import datetime

        mock_instance = MagicMock()
        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        mock_record = MagicMock()
        mock_record.id = 1
        mock_record.action = "change"
        mock_record.get_changed_fields_dict.return_value = {"title": "new"}
        mock_record.changed_by_username = "admin"
        mock_record.change_time = datetime(2024, 1, 1)
        mock_record.change_message = "Changed title"

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_by_app_and_name",
                return_value=mock_model,
            ):
                with patch(
                    "openviper.admin.api.views.get_change_history",
                    new_callable=AsyncMock,
                    return_value=[mock_record],
                ):
                    response = await handler(
                        _mock_request(), app_label="myapp", model_name="Article", obj_id=1
                    )

        body = json.loads(response.body)
        assert "history" in body
        assert len(body["history"]) == 1
        assert body["history"][0]["changed_by"] == "admin"


# ---------------------------------------------------------------------------
# Legacy endpoints: list_instances
# ---------------------------------------------------------------------------


class TestListInstances:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "list_instances")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request(), model_name="Article")

    @pytest.mark.asyncio
    async def test_not_registered_raises_not_found(self):
        from openviper.admin.registry import NotRegistered

        router = _make_router()
        handler = _get_handler(router, "list_instances")

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                side_effect=NotRegistered("not found"),
            ):
                with pytest.raises(NotFound):
                    await handler(_mock_request(), model_name="NonExistent")

    @pytest.mark.asyncio
    async def test_returns_paginated_items(self):
        router = _make_router()
        handler = _get_handler(router, "list_instances")

        mock_instance = MagicMock()
        mock_instance.id = 7
        mock_instance.title = "Test"

        mock_model_admin = MagicMock()
        mock_model_admin.list_per_page = 10
        mock_model_admin.get_list_display.return_value = ["title"]
        mock_model_admin.get_search_fields.return_value = []
        mock_model_admin.get_ordering.return_value = []

        qs = _make_qs(items=[mock_instance], total=1)
        mock_model = MagicMock()
        mock_model.objects.all.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(
                            _mock_request(query_params={"page": "1", "page_size": "10"}),
                            model_name="Article",
                        )

        body = json.loads(response.body)
        assert body["total"] == 1
        assert len(body["items"]) == 1


# ---------------------------------------------------------------------------
# Legacy: create_instance
# ---------------------------------------------------------------------------


class TestCreateInstance:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "create_instance")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request(), model_name="Article")

    @pytest.mark.asyncio
    async def test_successful_create_returns_201(self):
        router = _make_router()
        handler = _get_handler(router, "create_instance")

        mock_instance = MagicMock()
        mock_instance.id = 10
        mock_instance.save = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_add_permission.return_value = True
        mock_model_admin.get_readonly_fields.return_value = []

        mock_model = MagicMock()
        mock_model._fields = {}
        mock_model.return_value = mock_instance

        req = _mock_request(json_data={"title": "Article"})
        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch("openviper.admin.api.views.log_change", new_callable=AsyncMock):
                        response = await handler(req, model_name="Article")

        assert response.status_code == 201


# ---------------------------------------------------------------------------
# Legacy: get_instance
# ---------------------------------------------------------------------------


class TestGetInstance:
    @pytest.mark.asyncio
    async def test_instance_not_found_raises_not_found(self):
        router = _make_router()
        handler = _get_handler(router, "get_instance")

        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=None)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name", return_value=MagicMock()
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with pytest.raises(NotFound):
                        await handler(_mock_request(), model_name="Article", obj_id=99)


# ---------------------------------------------------------------------------
# Legacy: delete_instance
# ---------------------------------------------------------------------------


class TestDeleteInstance:
    @pytest.mark.asyncio
    async def test_successful_delete(self):
        router = _make_router()
        handler = _get_handler(router, "delete_instance")

        mock_instance = MagicMock()
        mock_instance.delete = AsyncMock()

        mock_model_admin = MagicMock()
        mock_model_admin.has_delete_permission.return_value = True
        mock_model = MagicMock()
        mock_model.objects.get_or_none = AsyncMock(return_value=mock_instance)

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch("openviper.admin.api.views.log_change", new_callable=AsyncMock):
                        response = await handler(_mock_request(), model_name="Article", obj_id=1)

        body = json.loads(response.body)
        assert "deleted" in body["detail"].lower()
        mock_instance.delete.assert_awaited_once()


# ---------------------------------------------------------------------------
# Legacy: get_filter_options
# ---------------------------------------------------------------------------


class TestGetFilterOptions:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "get_filter_options")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request(), model_name="Article")

    @pytest.mark.asyncio
    async def test_returns_filter_options(self):
        router = _make_router()
        handler = _get_handler(router, "get_filter_options")

        mock_model_admin = MagicMock()
        mock_model_admin.list_filter = ["status"]
        mock_model = MagicMock()
        mock_field = MagicMock()
        mock_field.__class__.__name__ = "CharField"
        mock_field.choices = [("a", "A"), ("b", "B")]
        mock_model._fields = {"status": mock_field}

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_name", return_value=mock_model
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(_mock_request(), model_name="Article")

        body = json.loads(response.body)
        assert "filters" in body


# ---------------------------------------------------------------------------
# list_plugins endpoint
# ---------------------------------------------------------------------------


class TestListPlugins:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "list_plugins")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request())

    @pytest.mark.asyncio
    async def test_returns_plugins_list(self):
        router = _make_router()
        handler = _get_handler(router, "list_plugins")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=True),
            patch("openviper.admin.api.views.settings") as ms,
        ):
            ms.INSTALLED_APPS = ["myapp"]
            response = await handler(_mock_request())

        body = json.loads(response.body)
        assert "plugins" in body


# ---------------------------------------------------------------------------
# export_instances_by_app endpoint
# ---------------------------------------------------------------------------


class TestExportInstancesByApp:
    @pytest.mark.asyncio
    async def test_no_admin_access_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "export_instances_by_app")

        with (
            patch("openviper.admin.api.views.check_admin_access", return_value=False),
            pytest.raises(PermissionDenied),
        ):
            await handler(_mock_request(), app_label="myapp", model_name="Article")

    @pytest.mark.asyncio
    async def test_no_view_permission_raises_permission_denied(self):
        router = _make_router()
        handler = _get_handler(router, "export_instances_by_app")

        mock_model_admin = MagicMock()
        mock_model = MagicMock()

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=False
                    ):
                        with pytest.raises(PermissionDenied):
                            await handler(_mock_request(), app_label="myapp", model_name="Article")

    @pytest.mark.asyncio
    async def test_returns_csv_response(self):
        router = _make_router()
        handler = _get_handler(router, "export_instances_by_app")

        mock_instance = MagicMock()
        mock_instance.id = 1
        mock_instance.title = "Test"

        mock_model_admin = MagicMock()
        mock_model_admin.get_list_display.return_value = ["title"]
        mock_model = MagicMock()
        qs = _make_qs(items=[mock_instance])
        mock_model.objects.all.return_value = qs

        with patch("openviper.admin.api.views.check_admin_access", return_value=True):
            with patch(
                "openviper.admin.api.views.admin.get_model_admin_by_app_and_name",
                return_value=mock_model_admin,
            ):
                with patch(
                    "openviper.admin.api.views.admin.get_model_by_app_and_name",
                    return_value=mock_model,
                ):
                    with patch(
                        "openviper.admin.api.views.check_model_permission", return_value=True
                    ):
                        response = await handler(
                            _mock_request(query_params={}),
                            app_label="myapp",
                            model_name="Article",
                        )

        assert response.status_code == 200
        assert "text/csv" in response.headers.get("Content-Type", "")
