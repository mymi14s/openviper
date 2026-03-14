"""Unit tests for uncovered logic in openviper.admin.api.views."""

from unittest.mock import patch

from openviper.admin.api import views


def test_is_auth_user_model_true():
    # Patch get_user_model to return the same class
    class User:
        pass

    with patch("openviper.admin.api.views.get_user_model", return_value=User):
        assert views._is_auth_user_model(User) is True

        # Subclass
        class SubUser(User):
            pass

        assert views._is_auth_user_model(SubUser) is True


def test_is_auth_user_model_false():
    class User:
        pass

    class Other:
        pass

    with patch("openviper.admin.api.views.get_user_model", return_value=User):
        assert views._is_auth_user_model(Other) is False


def test_is_auth_user_model_exception():
    # Simulate get_user_model raising
    with patch("openviper.admin.api.views.get_user_model", side_effect=Exception):

        class Dummy:
            pass

        assert views._is_auth_user_model(Dummy) is False
