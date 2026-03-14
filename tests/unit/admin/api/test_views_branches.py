"""Unit tests for missing branches in openviper.admin.api.views."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy.exc

from openviper.admin.api.views import _batch_load_children, _is_auth_user_model, get_admin_router
from openviper.exceptions import PermissionDenied


class TestIsAuthUserModel:
    """Test _is_auth_user_model helper function."""

    def test_returns_true_for_auth_user_model(self):
        """Should return True when model is the AUTH_USER_MODEL."""
        mock_user_model = MagicMock()

        with patch("openviper.admin.api.views.get_user_model", return_value=mock_user_model):
            result = _is_auth_user_model(mock_user_model)

            assert result is True

    def test_returns_true_for_subclass_of_auth_user_model(self):
        """Should return True when model is a subclass of AUTH_USER_MODEL."""

        class BaseUser:
            pass

        class CustomUser(BaseUser):
            pass

        with patch("openviper.admin.api.views.get_user_model", return_value=BaseUser):
            result = _is_auth_user_model(CustomUser)

            assert result is True

    def test_returns_false_for_different_model(self):
        """Should return False when model is not the AUTH_USER_MODEL."""

        class User:
            pass

        class Product:
            pass

        with patch("openviper.admin.api.views.get_user_model", return_value=User):
            result = _is_auth_user_model(Product)

            assert result is False

    def test_handles_exception_in_get_user_model(self):
        """Should return False when get_user_model raises an exception."""

        class SomeModel:
            pass

        with patch("openviper.admin.api.views.get_user_model", side_effect=RuntimeError("Error")):
            result = _is_auth_user_model(SomeModel)

            assert result is False

    def test_handles_exception_in_issubclass(self):
        """Should return False when issubclass raises an exception."""

        class User:
            pass

        # Pass something that's not a class to trigger TypeError in issubclass
        with patch("openviper.admin.api.views.get_user_model", return_value=User):
            result = _is_auth_user_model("not_a_class")  # type: ignore

            assert result is False


class TestBatchLoadChildren:
    """Test _batch_load_children edge cases."""

    @pytest.mark.asyncio
    async def test_returns_empty_dict_for_empty_instances(self):
        """Should return empty dict when instances list is empty."""
        mock_model_admin = MagicMock()
        mock_model_class = MagicMock()

        result = await _batch_load_children(mock_model_admin, mock_model_class, [])

        assert result == {}


class TestAdminRouterCreation:
    """Test get_admin_router function."""

    def test_creates_router_successfully(self):
        """Should create router with admin endpoints."""
        router = get_admin_router()

        # Should return a Router instance
        assert router is not None
        # Should have routes registered
        assert len(router.routes) > 0


class TestEndpointPermissionChecks:
    """Test that permission checks are properly enforced in all endpoints."""

    def setup_method(self):
        """Set up router for each test."""
        self.router = get_admin_router()

    def find_endpoint(self, path_pattern: str, method: str = "GET"):
        """Helper to find endpoint handler by path and method."""
        for route in self.router.routes:
            if (
                hasattr(route, "path")
                and str(route.path) == path_pattern
                and hasattr(route, "methods")
                and method in route.methods
            ):
                return route.handler
        return None

    @pytest.mark.asyncio
    async def test_change_password_requires_admin_access(self):
        """Should check admin access for change_password endpoint - line 484."""
        handler = self.find_endpoint("/api/users/{user_id}/change-password/", "POST")
        if handler:
            mock_request = MagicMock()
            mock_request.user = MagicMock(is_superuser=True)
            mock_request.json = AsyncMock(
                return_value={"new_password": "test", "confirm_password": "test"}
            )

            with patch("openviper.admin.api.views.check_admin_access", return_value=False):
                with pytest.raises(PermissionDenied, match="Admin access required"):
                    await handler(mock_request, user_id="1")

    @pytest.mark.asyncio
    async def test_get_model_config_requires_admin_access(self):
        """Should check admin access for get_model_config endpoint - line 613."""
        handler = self.find_endpoint("/api/models/{app_label}/{model_name}/", "GET")
        if handler:
            mock_request = MagicMock()

            with patch("openviper.admin.api.views.check_admin_access", return_value=False):
                with pytest.raises(PermissionDenied, match="Admin access required"):
                    await handler(mock_request, app_label="app", model_name="model")

    @pytest.mark.asyncio
    async def test_get_field_choices_requires_admin_access(self):
        """Should check admin access for get_field_choices endpoint - line 632."""
        handler = self.find_endpoint("/api/{model_name}/field-choices/{field_name}/", "GET")
        if handler:
            mock_request = MagicMock()

            with patch("openviper.admin.api.views.check_admin_access", return_value=False):
                with pytest.raises(PermissionDenied, match="Admin access required"):
                    await handler(mock_request, model_name="test", field_name="status")

    @pytest.mark.asyncio
    async def test_upload_file_requires_admin_access(self):
        """Should check admin access for upload_file endpoint - line 758."""
        handler = self.find_endpoint("/api/{model_name}/upload/", "POST")
        if handler:
            mock_request = MagicMock()
            mock_request.form = AsyncMock(return_value={})

            with patch("openviper.admin.api.views.check_admin_access", return_value=False):
                with pytest.raises(PermissionDenied, match="Admin access required"):
                    await handler(mock_request, model_name="test")


class TestFormDataJsonParsing:
    """Test FormData JSON parsing with fallback - lines 777-778, 925-935."""

    @pytest.mark.asyncio
    async def test_create_view_handles_invalid_json_in_formdata(self):
        """Should handle JSONDecodeError in create_view FormData parsing - lines 777-778."""
        router = get_admin_router()
        handler = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and str(route.path) == "/api/{model_name}/"
                and hasattr(route, "methods")
                and "POST" in route.methods
            ):
                handler = route.handler
                break

        if handler:
            mock_request = MagicMock()
            mock_request.headers = {"content-type": "multipart/form-data"}
            # FormData with invalid JSON string
            mock_request.form = AsyncMock(return_value={"data": "{invalid json}"})

            mock_model_admin = MagicMock()
            mock_model_admin.has_add_permission.return_value = True
            mock_model_admin.get_readonly_fields.return_value = []
            mock_model_admin.list_children.return_value = []

            mock_model_class = MagicMock()
            mock_model_class._fields = {}
            mock_instance = MagicMock()
            mock_instance.id = 1
            mock_model_class.objects.create = AsyncMock(return_value=mock_instance)

            with patch("openviper.admin.api.views.check_admin_access", return_value=True):
                with patch("openviper.admin.registry.admin.get", return_value=mock_model_admin):
                    with patch(
                        "openviper.admin.registry.admin.get_model", return_value=mock_model_class
                    ):
                        with patch(
                            "openviper.admin.api.views.check_model_permission", return_value=True
                        ):
                            with patch(
                                "openviper.admin.api.views._serialize_instance", return_value={}
                            ):
                                # Should not raise - JSONDecodeError is caught and raw value is used
                                response = await handler(mock_request, model_name="test")
                                # Verify response was successful
                                assert response.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_update_view_handles_invalid_json_in_formdata(self):
        """Should handle JSONDecodeError in update_view FormData parsing - lines 932-933."""
        router = get_admin_router()
        handler = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and str(route.path) == "/api/{model_name}/{pk}/"
                and hasattr(route, "methods")
                and "PUT" in route.methods
            ):
                handler = route.handler
                break

        if handler:
            mock_request = MagicMock()
            mock_request.headers = {"content-type": "multipart/form-data"}
            mock_request.form = AsyncMock(return_value={"data": "[invalid json"})

            mock_model_admin = MagicMock()
            mock_model_admin.has_change_permission.return_value = True
            mock_model_admin.get_readonly_fields.return_value = []
            mock_model_admin.list_children.return_value = []

            mock_instance = MagicMock()
            mock_instance.id = 1
            mock_instance.to_dict = MagicMock(return_value={})

            mock_model_class = MagicMock()
            mock_model_class._fields = {}
            mock_model_class.objects.get_or_none = AsyncMock(return_value=mock_instance)

            with patch("openviper.admin.api.views.check_admin_access", return_value=True):
                with patch("openviper.admin.registry.admin.get", return_value=mock_model_admin):
                    with patch(
                        "openviper.admin.registry.admin.get_model", return_value=mock_model_class
                    ):
                        with patch(
                            "openviper.admin.api.views.check_model_permission", return_value=True
                        ):
                            with patch(
                                "openviper.admin.api.views._serialize_instance", return_value={}
                            ):
                                with patch(
                                    "openviper.admin.api.views.cast_to_pk_type", return_value=1
                                ):
                                    # Should not raise - JSONDecodeError is caught
                                    response = await handler(
                                        mock_request, model_name="test", pk="1"
                                    )
                                    assert response.status_code in (200, 201)


class TestUpdateViewExceptionHandling:
    """Test exception handling in update_view - lines 1055-1059."""

    @pytest.mark.asyncio
    async def test_update_view_handles_value_error(self):
        """Should return 422 on ValueError - line 1055-1056."""
        router = get_admin_router()
        handler = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and str(route.path) == "/api/{model_name}/{pk}/"
                and hasattr(route, "methods")
                and "PUT" in route.methods
            ):
                handler = route.handler
                break

        if handler:
            mock_request = MagicMock()
            mock_request.headers = {"content-type": "application/json"}
            mock_request.json = AsyncMock(return_value={"field": "value"})

            mock_model_admin = MagicMock()
            mock_model_admin.has_change_permission.return_value = True
            mock_model_admin.get_readonly_fields.return_value = []
            mock_model_admin.list_children.return_value = []

            mock_instance = MagicMock()
            mock_instance.id = 1
            mock_instance.to_dict = MagicMock(return_value={})
            # Make the update raise ValueError
            mock_instance.update = AsyncMock(side_effect=ValueError("Invalid value"))

            mock_model_class = MagicMock()
            mock_model_class._fields = {}
            mock_model_class.objects.get_or_none = AsyncMock(return_value=mock_instance)

            with patch("openviper.admin.api.views.check_admin_access", return_value=True):
                with patch("openviper.admin.registry.admin.get", return_value=mock_model_admin):
                    with patch(
                        "openviper.admin.registry.admin.get_model", return_value=mock_model_class
                    ):
                        with patch(
                            "openviper.admin.api.views.check_model_permission", return_value=True
                        ):
                            with patch("openviper.admin.api.views.cast_to_pk_type", return_value=1):
                                response = await handler(mock_request, model_name="test", pk="1")
                                # Should return 422 with error message
                                assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_update_view_handles_integrity_error(self):
        """Should return 422 on IntegrityError - lines 1057-1059."""
        router = get_admin_router()
        handler = None
        for route in router.routes:
            if (
                hasattr(route, "path")
                and str(route.path) == "/api/{model_name}/{pk}/"
                and hasattr(route, "methods")
                and "PUT" in route.methods
            ):
                handler = route.handler
                break

        if handler:
            mock_request = MagicMock()
            mock_request.headers = {"content-type": "application/json"}
            mock_request.json = AsyncMock(return_value={"field": "value"})

            mock_model_admin = MagicMock()
            mock_model_admin.has_change_permission.return_value = True
            mock_model_admin.get_readonly_fields.return_value = []
            mock_model_admin.list_children.return_value = []

            mock_instance = MagicMock()
            mock_instance.id = 1
            mock_instance.to_dict = MagicMock(return_value={})
            # Make the update raise IntegrityError
            orig_exc = Exception("UNIQUE constraint failed")
            integrity_error = sqlalchemy.exc.IntegrityError("statement", {}, orig_exc)
            integrity_error.orig = orig_exc
            mock_instance.update = AsyncMock(side_effect=integrity_error)

            mock_model_class = MagicMock()
            mock_model_class._fields = {}
            mock_model_class.objects.get_or_none = AsyncMock(return_value=mock_instance)

            with patch("openviper.admin.api.views.check_admin_access", return_value=True):
                with patch("openviper.admin.registry.admin.get", return_value=mock_model_admin):
                    with patch(
                        "openviper.admin.registry.admin.get_model", return_value=mock_model_class
                    ):
                        with patch(
                            "openviper.admin.api.views.check_model_permission", return_value=True
                        ):
                            with patch("openviper.admin.api.views.cast_to_pk_type", return_value=1):
                                response = await handler(mock_request, model_name="test", pk="1")
                                # Should return 422 with error message
                                assert response.status_code == 422
