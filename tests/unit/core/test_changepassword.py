"""Unit tests for changepassword management command."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from openviper.core.management.base import CommandError
from openviper.core.management.commands.changepassword import Command


@pytest.fixture
def command():
    return Command()


@pytest.fixture
def mock_user_model():
    mock_user = Mock()
    mock_user.username = "testuser"
    mock_user.set_password = AsyncMock()
    mock_user.save = AsyncMock()

    mock_model = Mock()
    mock_model._fields = {"username": Mock(), "email": Mock()}
    mock_model.objects.get_or_none = AsyncMock(return_value=mock_user)

    return mock_model, mock_user


class TestChangePasswordCommand:
    def test_help_attribute(self, command):
        assert command.help == "Change a user's password."

    def test_add_arguments(self, command):
        parser = Mock()
        parser.add_argument = Mock()

        command.add_arguments(parser)

        assert parser.add_argument.call_count == 2
        calls = parser.add_argument.call_args_list
        assert any("username" in str(call) for call in calls)
        assert any("--password" in str(call) for call in calls)

    def test_command_instantiation(self):
        cmd = Command()
        assert cmd is not None
        assert hasattr(cmd, "handle")
        assert hasattr(cmd, "add_arguments")


class TestHandleWithOptions:
    @patch("openviper.core.management.commands.changepassword.get_user_model")
    @patch("openviper.core.management.commands.changepassword.asyncio.run")
    def test_handle_with_username_and_password(
        self, mock_asyncio_run, mock_get_user_model, command, mock_user_model
    ):
        mock_model, mock_user = mock_user_model
        mock_get_user_model.return_value = mock_model

        command.handle(username="testuser", password="newpass123")

        mock_asyncio_run.assert_called_once()

    @patch("openviper.core.management.commands.changepassword.get_user_model")
    @patch("builtins.input", side_effect=["testuser"])
    @patch(
        "openviper.core.management.commands.changepassword.getpass.getpass",
        side_effect=["newpass", "newpass"],
    )
    def test_handle_prompts_for_username_and_password(
        self, mock_getpass, mock_input, mock_get_user_model, command, mock_user_model, capsys
    ):
        mock_model, mock_user = mock_user_model
        mock_get_user_model.return_value = mock_model

        command.handle(username=None, password=None)

        mock_input.assert_called_once()
        assert mock_getpass.call_count == 2

    @patch("openviper.core.management.commands.changepassword.get_user_model")
    @patch("builtins.input", return_value="")
    def test_handle_empty_username_raises_error(self, mock_input, mock_get_user_model, command):
        mock_model = Mock()
        mock_model._fields = {"username": Mock()}
        mock_get_user_model.return_value = mock_model

        with pytest.raises(CommandError) as exc_info:
            command.handle(username=None, password="pass")

        assert "Username is required" in str(exc_info.value)


class TestUserLookup:
    @patch("openviper.core.management.commands.changepassword.get_user_model")
    def test_handle_user_not_found(self, mock_get_user_model, command):
        mock_model = Mock()
        mock_model._fields = {"username": Mock()}
        mock_model.objects.get_or_none = AsyncMock(return_value=None)
        mock_get_user_model.return_value = mock_model

        with pytest.raises(CommandError, match="User 'nonexistent' not found"):
            command.handle(username="nonexistent", password="pass123")

    @patch("openviper.core.management.commands.changepassword.get_user_model")
    def test_handle_user_found_and_password_changed(
        self, mock_get_user_model, command, mock_user_model, capsys
    ):
        mock_model, mock_user = mock_user_model
        mock_get_user_model.return_value = mock_model

        command.handle(username="testuser", password="newpass")

        captured = capsys.readouterr()
        assert "Password changed successfully" in captured.out or "testuser" in captured.out


class TestPasswordValidation:
    @patch("openviper.core.management.commands.changepassword.get_user_model")
    @patch(
        "openviper.core.management.commands.changepassword.getpass.getpass",
        side_effect=["pass1", "pass2", "pass3", "pass3"],
    )
    def test_handle_password_mismatch_retries(
        self, mock_getpass, mock_get_user_model, command, mock_user_model, capsys
    ):
        mock_model, mock_user = mock_user_model
        mock_get_user_model.return_value = mock_model

        command.handle(username="testuser", password=None)

        assert mock_getpass.call_count == 4

    @patch("openviper.core.management.commands.changepassword.get_user_model")
    @patch(
        "openviper.core.management.commands.changepassword.getpass.getpass",
        side_effect=["", "pass", "pass"],
    )
    def test_handle_blank_password_retries(
        self, mock_getpass, mock_get_user_model, command, mock_user_model, capsys
    ):
        mock_model, mock_user = mock_user_model
        mock_get_user_model.return_value = mock_model

        command.handle(username="testuser", password=None)

        assert mock_getpass.call_count == 3

        captured = capsys.readouterr()
        assert "Password cannot be blank" in captured.err


class TestCancellation:
    @patch("openviper.core.management.commands.changepassword.get_user_model")
    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_handle_username_prompt_cancelled(
        self, mock_input, mock_get_user_model, command, capsys
    ):
        mock_model = Mock()
        mock_model._fields = {"username": Mock()}
        mock_get_user_model.return_value = mock_model

        command.handle(username=None, password="pass")

        captured = capsys.readouterr()
        assert "Operation cancelled" in captured.out

    @patch("openviper.core.management.commands.changepassword.get_user_model")
    @patch(
        "openviper.core.management.commands.changepassword.getpass.getpass",
        side_effect=KeyboardInterrupt,
    )
    def test_handle_password_prompt_cancelled(
        self, mock_getpass, mock_get_user_model, command, mock_user_model, capsys
    ):
        mock_model, mock_user = mock_user_model
        mock_get_user_model.return_value = mock_model

        command.handle(username="testuser", password=None)

        captured = capsys.readouterr()
        assert "Operation cancelled" in captured.out

    @patch("openviper.core.management.commands.changepassword.get_user_model")
    @patch("builtins.input", side_effect=EOFError)
    def test_handle_username_prompt_eof(self, mock_input, mock_get_user_model, command, capsys):
        mock_model = Mock()
        mock_model._fields = {"username": Mock()}
        mock_get_user_model.return_value = mock_model

        command.handle(username=None, password="pass")

        captured = capsys.readouterr()
        assert "Operation cancelled" in captured.out


class TestSuccessOutput:
    @patch("openviper.core.management.commands.changepassword.get_user_model")
    def test_handle_success_message(self, mock_get_user_model, command, mock_user_model, capsys):
        mock_model, mock_user = mock_user_model
        mock_get_user_model.return_value = mock_model

        command.handle(username="testuser", password="newpass")

        captured = capsys.readouterr()
        assert "Password changed successfully" in captured.out
        assert "testuser" in captured.out


class TestSetPasswordAwaited:
    @patch("openviper.core.management.commands.changepassword.get_user_model")
    def test_set_password_is_awaited(self, mock_get_user_model, command, mock_user_model, capsys):
        """set_password must be awaited since it is async."""
        mock_model, mock_user = mock_user_model
        mock_get_user_model.return_value = mock_model

        command.handle(username="testuser", password="newpass")

        mock_user.set_password.assert_awaited_once_with("newpass")
        mock_user.save.assert_awaited_once()


class TestEdgeCases:
    @patch("openviper.core.management.commands.changepassword.get_user_model")
    @patch("builtins.input", return_value="")
    def test_handle_with_empty_string_username(self, mock_input, mock_get_user_model, command):
        mock_model = Mock()
        mock_model._fields = {"username": Mock()}
        mock_get_user_model.return_value = mock_model

        with pytest.raises(CommandError, match="Username is required"):
            command.handle(username="", password="pass")

    @patch("openviper.core.management.commands.changepassword.get_user_model")
    @patch("builtins.input", return_value="  testuser  ")
    @patch(
        "openviper.core.management.commands.changepassword.getpass.getpass",
        side_effect=["pass", "pass"],
    )
    def test_handle_strips_whitespace_from_username(
        self, mock_getpass, mock_input, mock_get_user_model, command, mock_user_model
    ):
        mock_model, mock_user = mock_user_model
        mock_get_user_model.return_value = mock_model

        command.handle(username=None, password=None)

        mock_input.assert_called_once()
        mock_model.objects.get_or_none.assert_called_with(username="testuser")
