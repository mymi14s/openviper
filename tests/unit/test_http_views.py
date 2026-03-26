"""Unit tests for HTTP View authentication and permission defaults."""

from unittest.mock import MagicMock, patch

from openviper.http.views import View


class TestViewDefaults:
    def test_authentication_classes_default_is_none(self) -> None:
        """View.authentication_classes defaults to empty list."""
        from openviper.http.views import View

        assert View.authentication_classes == []

    def test_permission_classes_default_is_none(self) -> None:
        """View.permission_classes defaults to empty list."""
        from openviper.http.views import View

        assert View.permission_classes == []

    def test_explicit_empty_list_disables_auth(self) -> None:
        """Setting authentication_classes=[] should skip all authentication."""

        class OpenView(View):
            authentication_classes = []

        view = OpenView()
        authenticators = view.get_authenticators()
        assert authenticators == []

    def test_explicit_empty_list_disables_permissions(self) -> None:
        """Setting permission_classes=[] should skip all permission checks."""

        class OpenView(View):
            permission_classes = []

        view = OpenView()
        permissions = view.get_permissions()
        assert permissions == []

    def test_none_authenticators_falls_back_to_settings(self) -> None:
        """When None, get_authenticators() loads from settings."""

        class DefaultView(View):
            authentication_classes = None

        view = DefaultView()

        mock_auth_cls = MagicMock()
        mock_auth_instance = MagicMock()
        mock_auth_cls.return_value = mock_auth_instance

        with patch("openviper.http.views.settings") as mock_settings:
            mock_settings.DEFAULT_AUTHENTICATION_CLASSES = [mock_auth_cls]
            authenticators = view.get_authenticators()

        assert len(authenticators) == 1
        assert authenticators[0] is mock_auth_instance

    def test_none_permissions_falls_back_to_settings(self) -> None:
        """When None, get_permissions() loads from settings."""

        class DefaultView(View):
            permission_classes = None

        view = DefaultView()

        class FakePerm:
            pass

        with patch("openviper.http.views.settings") as mock_settings:
            mock_settings.DEFAULT_PERMISSION_CLASSES = [FakePerm]
            permissions = view.get_permissions()

        assert len(permissions) == 1
        assert isinstance(permissions[0], FakePerm)
