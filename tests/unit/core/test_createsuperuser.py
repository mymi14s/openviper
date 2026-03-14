"""Unit tests for createsuperuser management command."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from openviper.core.management.base import CommandError
from openviper.core.management.commands.createsuperuser import (
    Command,
    _validate_email,
    _validate_username,
)


@pytest.fixture
def command():
    """Create a Command instance."""
    return Command()


@pytest.fixture
def mock_user_model():
    """Create a mock User model."""

    def create_mock_user(**kwargs):
        mock_user = Mock()
        mock_user.username = kwargs.get("username", "testuser")
        mock_user.email = kwargs.get("email", "test@example.com")
        mock_user.set_password = AsyncMock()
        mock_user.save = AsyncMock()
        return mock_user

    mock_model = Mock(side_effect=create_mock_user)
    mock_model._fields = {
        "username": object(),
        "email": object(),
        "is_superuser": object(),
        "is_staff": object(),
        "is_active": object(),
    }
    mock_model.objects.get_or_none = AsyncMock(return_value=None)

    return mock_model, create_mock_user()


class TestValidationFunctions:
    """Test validation helper functions."""

    def test_validate_username_valid(self):
        assert _validate_username("testuser") is None
        assert _validate_username("user123") is None
        assert _validate_username("test_user") is None
        assert _validate_username("test.user@domain") is None

    def test_validate_username_empty(self):
        error = _validate_username("")
        assert error is not None
        assert "cannot be blank" in error

    def test_validate_username_invalid_chars(self):
        error = _validate_username("test user!")
        assert error is not None
        assert "Invalid username" in error

    def test_validate_username_too_long(self):
        error = _validate_username("a" * 151)
        assert error is not None
        assert "Invalid username" in error

    def test_validate_email_valid(self):
        assert _validate_email("test@example.com") is None
        assert _validate_email("user+tag@domain.co.uk") is None

    def test_validate_email_empty(self):
        error = _validate_email("")
        assert error is not None
        assert "cannot be blank" in error

    def test_validate_email_invalid(self):
        error = _validate_email("invalid-email")
        assert error is not None
        assert "valid email" in error


class TestCreateSuperuserCommand:
    """Test createsuperuser command basic functionality."""

    def test_help_attribute(self, command):
        assert "superuser" in command.help.lower()

    def test_add_arguments(self, command):
        parser = Mock()
        parser.add_argument = Mock()

        command.add_arguments(parser)

        # Should add --username, --email, --password, --no-input
        assert parser.add_argument.call_count == 4

        calls = parser.add_argument.call_args_list
        assert any("--username" in str(call) for call in calls)
        assert any("--email" in str(call) for call in calls)
        assert any("--password" in str(call) for call in calls)
        assert any("--no-input" in str(call) for call in calls)


class TestPromptMethods:
    """Test prompt helper methods."""

    @patch("builtins.input", return_value="validuser")
    def test_prompt_username_valid(self, mock_input, command):
        username = command._prompt_username(None)
        assert username == "validuser"

    def test_prompt_username_with_preset(self, command):
        username = command._prompt_username("preset_user")
        assert username == "preset_user"

    def test_prompt_username_preset_invalid_raises_error(self, command):
        with pytest.raises(CommandError) as exc_info:
            command._prompt_username("invalid user!")

        assert "Invalid username" in str(exc_info.value)

    @patch("builtins.input", side_effect=["", "validuser"])
    def test_prompt_username_retries_on_empty(self, mock_input, command, capsys):
        username = command._prompt_username(None)
        assert username == "validuser"
        assert mock_input.call_count == 2

    @patch("builtins.input", return_value="test@example.com")
    def test_prompt_email_valid(self, mock_input, command):
        email = command._prompt_email(None)
        assert email == "test@example.com"

    def test_prompt_email_with_preset(self, command):
        email = command._prompt_email("preset@example.com")
        assert email == "preset@example.com"

    @patch("getpass.getpass", side_effect=["password123", "password123"])
    def test_prompt_password_matching(self, mock_getpass, command):
        password = command._prompt_password(None)
        assert password == "password123"
        assert mock_getpass.call_count == 2

    def test_prompt_password_with_preset(self, command):
        password = command._prompt_password("preset_pass")
        assert password == "preset_pass"

    @patch("getpass.getpass", side_effect=["pass1", "pass2", "pass3", "pass3"])
    def test_prompt_password_retries_on_mismatch(self, mock_getpass, command, capsys):
        password = command._prompt_password(None)
        assert password == "pass3"
        assert mock_getpass.call_count == 4

        captured = capsys.readouterr()
        assert "do not match" in captured.err

    @patch("getpass.getpass", side_effect=["", "password", "password"])
    def test_prompt_password_retries_on_blank(self, mock_getpass, command, capsys):
        password = command._prompt_password(None)
        assert password == "password"

        captured = capsys.readouterr()
        assert "cannot be blank" in captured.err


class TestHandleNoInput:
    """Test --no-input mode."""

    @patch("openviper.core.management.commands.createsuperuser.get_user_model")
    @patch("openviper.core.management.commands.createsuperuser.asyncio.run")
    def test_handle_no_input_with_all_options(
        self, mock_run, mock_get_user_model, command, mock_user_model
    ):
        mock_model, mock_user = mock_user_model
        mock_get_user_model.return_value = mock_model

        def close_coro(coro):
            coro.close()

        mock_run.side_effect = close_coro

        command.handle(
            username="admin",
            email="admin@example.com",
            password="adminpass",
            no_input=True,
        )

        mock_run.assert_called_once()

    @patch("openviper.core.management.commands.createsuperuser.get_user_model")
    def test_handle_no_input_missing_username_raises_error(self, mock_get_user_model, command):
        with pytest.raises(CommandError) as exc_info:
            command.handle(
                username=None,
                email="admin@example.com",
                password="pass",
                no_input=True,
            )

        assert "--username, --email, and --password are required" in str(exc_info.value)

    @patch("openviper.core.management.commands.createsuperuser.get_user_model")
    def test_handle_no_input_invalid_email_raises_error(self, mock_get_user_model, command):
        with pytest.raises(CommandError) as exc_info:
            command.handle(
                username="admin",
                email="invalid-email",
                password="pass",
                no_input=True,
            )

        assert "valid email" in str(exc_info.value)


class TestHandleInteractive:
    """Test interactive mode."""

    @patch("openviper.core.management.commands.createsuperuser.get_user_model")
    @patch.object(Command, "_prompt_username")
    @patch.object(Command, "_prompt_email")
    @patch.object(Command, "_prompt_password")
    @patch("openviper.core.management.commands.createsuperuser.asyncio.run")
    def test_handle_interactive_prompts_all_fields(
        self,
        mock_run,
        mock_prompt_pass,
        mock_prompt_email,
        mock_prompt_user,
        mock_get_user_model,
        command,
        mock_user_model,
    ):
        mock_model, mock_user = mock_user_model
        mock_get_user_model.return_value = mock_model

        mock_prompt_user.return_value = "interactive_user"
        mock_prompt_email.return_value = "user@example.com"
        mock_prompt_pass.return_value = "password123"

        def close_coro(coro):
            coro.close()

        mock_run.side_effect = close_coro

        command.handle(username=None, email=None, password=None, no_input=False)

        mock_prompt_user.assert_called_once()
        mock_prompt_email.assert_called_once()
        mock_prompt_pass.assert_called_once()


class TestUserCreation:
    """Test user creation logic."""

    @patch("openviper.core.management.commands.createsuperuser.get_user_model")
    def test_handle_creates_superuser(self, mock_get_user_model, command, mock_user_model, capsys):
        mock_model, mock_user = mock_user_model
        mock_get_user_model.return_value = mock_model

        command.handle(
            username="admin", email="admin@example.com", password="password", no_input=True
        )

        captured = capsys.readouterr()
        assert "Superuser 'admin' created successfully" in captured.out

    @patch("openviper.core.management.commands.createsuperuser.get_user_model")
    def test_handle_existing_username_raises_error(self, mock_get_user_model, command):
        mock_model = Mock()
        mock_model.objects.get_or_none = AsyncMock(return_value=Mock())
        mock_get_user_model.return_value = mock_model

        with pytest.raises(CommandError, match="A user with username 'existing' already exists."):
            command.handle(
                username="existing", email="test@example.com", password="pwd", no_input=True
            )

    @patch("openviper.core.management.commands.createsuperuser.get_user_model")
    def test_handle_existing_email_raises_error(self, mock_get_user_model, command):
        mock_model = Mock()
        # First call returns None (username check), second returns user (email check)
        mock_model.objects.get_or_none = AsyncMock(
            side_effect=[None, Mock(email="existing@example.com")]
        )
        mock_get_user_model.return_value = mock_model

        with pytest.raises(
            CommandError, match="A user with email 'existing@example.com' already exists."
        ):
            command.handle(
                username="newuser", email="existing@example.com", password="pwd", no_input=True
            )


class TestSuperuserAttributes:
    """Test that created user has correct superuser attributes."""

    @patch("openviper.core.management.commands.createsuperuser.get_user_model")
    def test_handle_sets_superuser_flags(self, mock_get_user_model, command, mock_user_model):
        mock_model, mock_user = mock_user_model
        mock_get_user_model.return_value = mock_model

        command.handle(username="admin", email="admin@example.com", password="pwd", no_input=True)

        create_kwargs = mock_model.call_args[1]
        assert create_kwargs["is_superuser"] is True
        assert create_kwargs["is_staff"] is True
        assert create_kwargs["is_active"] is True


class TestSetPasswordAwaited:
    """Test that set_password is properly awaited (async)."""

    @patch("openviper.core.management.commands.createsuperuser.get_user_model")
    def test_set_password_is_awaited(self, mock_get_user_model, command, mock_user_model, capsys):
        """set_password must be awaited since it is async."""
        mock_model, _ = mock_user_model
        mock_get_user_model.return_value = mock_model

        # Track the user created by the side_effect
        created_users = []
        original_side_effect = mock_model.side_effect

        def tracking_create(**kwargs):
            user = original_side_effect(**kwargs)
            created_users.append(user)
            return user

        mock_model.side_effect = tracking_create

        command.handle(
            username="admin",
            email="admin@example.com",
            password="secret",
            no_input=True,
        )

        assert len(created_users) == 1
        created_user = created_users[0]
        created_user.set_password.assert_awaited_once_with("secret")
        created_user.save.assert_awaited_once()


class TestCustomUserModelSupport:
    """Test custom user models with non-standard required fields."""

    @patch("openviper.core.management.commands.createsuperuser.get_user_model")
    def test_handle_custom_model_sets_name_and_password_before_save(
        self, mock_get_user_model, command, capsys
    ):
        created_users = []

        def build_user(**kwargs):
            user = Mock()
            user.name = kwargs.get("name")
            user.email = kwargs.get("email")
            user.set_password = AsyncMock()
            user.save = AsyncMock()
            created_users.append(user)
            return user

        custom_model = Mock(side_effect=build_user)
        custom_model._fields = {
            "name": object(),
            "email": object(),
            "password_hash": object(),
        }
        custom_model.objects.get_or_none = AsyncMock(side_effect=[None, None])
        mock_get_user_model.return_value = custom_model

        command.handle(
            username="admin",
            email="admin@example.com",
            password="secret",
            no_input=True,
        )

        assert len(created_users) == 1
        created_user = created_users[0]
        assert custom_model.call_args.kwargs["name"] == "admin"
        assert custom_model.call_args.kwargs["email"] == "admin@example.com"
        created_user.set_password.assert_awaited_once_with("secret")
        created_user.save.assert_awaited_once()

        captured = capsys.readouterr()
        assert "missing admin flags" in captured.err


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_command_instantiation(self):
        """Test that command can be instantiated."""
        cmd = Command()
        assert cmd is not None
        assert hasattr(cmd, "handle")
        assert hasattr(cmd, "_prompt_username")
        assert hasattr(cmd, "_prompt_email")
        assert hasattr(cmd, "_prompt_password")

    def test_validate_username_regex_pattern(self):
        """Test username validation regex."""
        # Valid usernames
        assert _validate_username("user") is None
        assert _validate_username("user_123") is None
        assert _validate_username("user.name@domain") is None
        assert _validate_username("user+tag") is None
        assert _validate_username("user-name") is None

        # Invalid usernames
        assert _validate_username("user name") is not None  # space
        assert _validate_username("user!name") is not None  # invalid char

    def test_validate_email_regex_pattern(self):
        """Test email validation regex."""
        # Valid emails
        assert _validate_email("simple@example.com") is None
        assert _validate_email("user+tag@domain.com") is None
        assert _validate_email("user.name@sub.domain.com") is None

        # Invalid emails
        assert _validate_email("notanemail") is not None
        assert _validate_email("@example.com") is not None
        assert _validate_email("user@") is not None
        assert _validate_email("user @example.com") is not None
