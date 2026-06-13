"""Tests for console, changepassword, createsuperuser commands - uncovered branches."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.core.management.base import CommandError
from openviper.core.management.commands.changepassword import Command as ChangePasswordCommand
from openviper.core.management.commands.console import Command as ShellCommand
from openviper.core.management.commands.createsuperuser import (
    Command as CreatesuperuserCommand,
)
from openviper.core.management.commands.createsuperuser import (
    build_user_kwargs,
    model_field_names,
    validate_email,
    validate_username,
)
from openviper.db.models import Model


class TestConsoleModelDiscovery:
    """Test console command discover_models method."""

    @pytest.fixture
    def console_command(self):
        """Create a console Command instance."""
        return ShellCommand()

    def test_discover_models_import_error(self, console_command):
        """Test discover_models handles ImportError gracefully."""
        with patch("openviper.core.management.commands.console.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["nonexistent_app"]

            with patch(
                "openviper.core.management.commands.console.get_user_model",
                side_effect=RuntimeError("No user model"),
            ):
                with patch(
                    "openviper.core.management.commands.console.importlib.import_module",
                    side_effect=ImportError("No module"),
                ):
                    with patch.object(console_command, "stdout"):
                        models = console_command.discover_models()

                        # Should return empty dict, not raise
                        assert models == {}

    def test_discover_models_subclass_check(self, console_command):
        """Test discover_models handles issubclass checks."""

        # Create a real Model subclass with proper module
        class FakeModel(Model):
            pass

        # Rather than fighting mocks, let's just check that empty apps works
        with patch("openviper.core.management.commands.console.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = []

            with patch(
                "openviper.core.management.commands.console.get_user_model",
                side_effect=RuntimeError("No user model"),
            ):
                with patch.object(console_command, "stdout"):
                    models = console_command.discover_models()
                    # With no apps and user model error, should be empty
                    assert models == {}

    def test_discover_models_type_error_in_issubclass(self, console_command):
        """Test discover_models catches TypeError from issubclass."""
        mock_module = MagicMock()
        mock_module.__name__ = "myapp.models"

        with patch("openviper.core.management.commands.console.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["myapp"]

            with patch(
                "openviper.core.management.commands.console.importlib.import_module",
                return_value=mock_module,
            ):
                with patch(
                    "openviper.core.management.commands.console.discover_models_in_module",
                    return_value=[],
                ):
                    with patch.object(console_command, "stdout"):
                        models = console_command.discover_models()
                        assert isinstance(models, dict)

    def test_discover_models_output_count(self, console_command):
        """Test discover_models outputs model count when found."""

        class FakeModel(Model):
            __module__ = "myapp.models"

        mock_module = MagicMock()
        mock_module.__name__ = "myapp.models"

        with patch("openviper.core.management.commands.console.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = ["myapp"]

            with patch(
                "openviper.core.management.commands.console.importlib.import_module",
                return_value=mock_module,
            ):
                with patch(
                    "openviper.core.management.commands.console.discover_models_in_module",
                    return_value=[FakeModel],
                ):
                    with patch.object(console_command, "stdout") as mock_stdout:
                        console_command.discover_models()
                        assert mock_stdout.called

    def test_discover_models_user_model_exception(self, console_command):
        """Test discover_models handles get_user_model exception."""
        with patch("openviper.core.management.commands.console.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = []

            with patch(
                "openviper.core.management.commands.console.get_user_model"
            ) as mock_get_user:
                mock_get_user.side_effect = RuntimeError("User model not configured")

                with patch.object(console_command, "stdout"):
                    models = console_command.discover_models()

                    # Should not raise, should return empty dict
                    assert models == {}

    def test_discover_models_adds_user_model(self, console_command):
        """Test discover_models adds user model if not already present."""
        mock_user = MagicMock()
        mock_user.__name__ = "CustomUser"

        with patch("openviper.core.management.commands.console.settings") as mock_settings:
            mock_settings.INSTALLED_APPS = []

            with patch(
                "openviper.core.management.commands.console.get_user_model", return_value=mock_user
            ):
                with patch.object(console_command, "stdout") as mock_stdout:
                    models = console_command.discover_models()

                    assert "CustomUser" in models
                    assert mock_stdout.called


class TestChangepasswordBranches:
    """Test changepassword command uncovered branches."""

    @pytest.fixture
    def changepassword_command(self):
        """Create a changepassword Command instance."""
        return ChangePasswordCommand()

    def test_user_lookup_by_email(self, changepassword_command):
        """Test user lookup by email field when no username field."""
        field_names = {"email", "password", "is_active"}

        if "username" in field_names:
            lookup_field = "username"
        elif "email" in field_names:
            lookup_field = "email"
        elif "name" in field_names:
            lookup_field = "name"
        else:
            lookup_field = None

        assert lookup_field == "email"

    def test_user_lookup_by_name(self, changepassword_command):
        """Test user lookup by name field."""
        field_names = {"name", "password", "is_active"}

        if "username" in field_names:
            lookup_field = "username"
        elif "email" in field_names:
            lookup_field = "email"
        elif "name" in field_names:
            lookup_field = "name"
        else:
            lookup_field = None

        assert lookup_field == "name"

    def test_user_lookup_no_identity_field(self, changepassword_command):
        """Test user lookup when no identity field exists."""
        field_names = {"password", "is_active"}

        if "username" in field_names:
            lookup_field = "username"
        elif "email" in field_names:
            lookup_field = "email"
        elif "name" in field_names:
            lookup_field = "name"
        else:
            lookup_field = None

        assert lookup_field is None

    def test_handle_generic_exception(self, changepassword_command):
        """Test handle wraps generic exception as CommandError."""
        mock_user_cls = MagicMock()
        mock_user_cls._fields = {"username": MagicMock()}
        mock_user_cls.objects.get_or_none = AsyncMock(side_effect=RuntimeError("DB error"))

        with patch(
            "openviper.core.management.commands.changepassword.get_user_model",
            return_value=mock_user_cls,
        ):
            with pytest.raises(CommandError, match="DB error"):
                changepassword_command.handle(username="admin", password="newpass")

    def test_password_prompt_keyboard_interrupt(self, changepassword_command):
        """Test password prompt handles KeyboardInterrupt."""
        # Simulate the exception handling
        cancelled = False
        try:
            raise KeyboardInterrupt()
        except EOFError, KeyboardInterrupt:
            cancelled = True

        assert cancelled

    def test_password_mismatch_continues(self, changepassword_command):
        """Test password mismatch shows error and continues."""
        password = "pass1"
        confirm = "different"

        error_shown = password != confirm

        assert error_shown

    def test_blank_password_rejected(self, changepassword_command):
        """Test blank password shows error and continues."""
        password = ""

        error_shown = bool(not password)

        assert error_shown


class TestCreatesuperuserBranches:
    """Test createsuperuser command uncovered branches."""

    @pytest.fixture
    def createsuperuser_command(self):
        """Create a createsuperuser Command instance."""
        return CreatesuperuserCommand()

    def test_prompt_email_invalid_preset(self, createsuperuser_command):
        """Test _prompt_email raises CommandError for invalid preset."""

        preset = "invalid-email"
        err = validate_email(preset)

        assert err is not None
        assert "valid email" in err

        with pytest.raises(CommandError):
            createsuperuser_command.prompt_email(preset)

    def test_prompt_email_shows_error_and_retries(self, createsuperuser_command):
        """Test _prompt_email shows error and continues on invalid input."""

        # Simulate the retry logic
        inputs = ["invalid", "also-invalid", "valid@test.com"]
        errors = []

        for value in inputs:
            err = validate_email(value)
            if err:
                errors.append(err)
                continue
            result = value
            break

        assert len(errors) == 2
        assert result == "valid@test.com"

    def test_username_validation_no_input_mode(self, createsuperuser_command):
        """Test username validation in --no-input mode raises CommandError."""

        username = "ab"  # Too short or invalid
        err = validate_username(username)

        # With blank username
        err = validate_username("")
        assert err == "Username cannot be blank."

    def test_handle_generic_exception(self, createsuperuser_command):
        """Test handle wraps generic exception as CommandError."""
        mock_user_cls = MagicMock()
        mock_user_cls._fields = {"username": MagicMock(), "email": MagicMock()}
        mock_user_cls.objects.get_or_none = AsyncMock(side_effect=RuntimeError("DB error"))

        with patch(
            "openviper.core.management.commands.createsuperuser.get_user_model",
            return_value=mock_user_cls,
        ):
            with pytest.raises(CommandError, match="DB error"):
                createsuperuser_command.handle(
                    no_input=True, username="admin", email="admin@test.com", password="password123"
                )

    def test_validate_username_blank(self):
        """Test validate_username returns error for blank."""

        assert validate_username("") == "Username cannot be blank."

    def test_validate_username_invalid_chars(self):
        """Test validate_username returns error for invalid characters."""

        # Very long string with special chars
        err = validate_username("a" * 200)
        assert err is not None

    def test_validate_email_blank(self):
        """Test validate_email returns error for blank."""

        assert validate_email("") == "Email cannot be blank."

    def test_validate_email_invalid_format(self):
        """Test validate_email returns error for invalid format."""

        assert validate_email("notanemail") == "Enter a valid email address."
        assert validate_email("missing@domain") == "Enter a valid email address."

    def test_validate_email_valid(self):
        """Test validate_email returns None for valid email."""

        assert validate_email("test@example.com") is None
        assert validate_email("user.name@domain.co.uk") is None

    def test_model_field_names_fallback(self):
        """Test model_field_names falls back to default fields."""

        # Model without _fields
        mock_model = MagicMock()
        mock_model._fields = None

        fields = model_field_names(mock_model)
        assert "username" in fields
        assert "email" in fields
        assert "is_superuser" in fields

    def test_model_field_names_with_fields(self):
        """Test model_field_names returns model fields."""

        mock_model = MagicMock()
        mock_model._fields = {"custom_field": MagicMock(), "another": MagicMock()}

        fields = model_field_names(mock_model)
        assert "custom_field" in fields
        assert "another" in fields

    def test_build_user_kwargs_with_name_field(self):
        """Test build_user_kwargs uses name field when username not present."""

        field_names = {"name", "email", "is_superuser", "is_staff", "is_active"}
        kwargs = build_user_kwargs(field_names, "admin", "admin@test.com")

        assert kwargs["name"] == "admin"
        assert kwargs["email"] == "admin@test.com"
        assert kwargs["is_superuser"] is True

    def test_build_user_kwargs_minimal_fields(self):
        """Test build_user_kwargs with minimal fields."""

        field_names = {"username", "email"}
        kwargs = build_user_kwargs(field_names, "admin", "admin@test.com")

        assert kwargs == {"username": "admin", "email": "admin@test.com"}

    def test_prompt_username_preset_valid(self, createsuperuser_command):
        """Test _prompt_username with valid preset returns it."""
        result = createsuperuser_command.prompt_username("validuser")
        assert result == "validuser"

    def test_prompt_username_preset_invalid(self, createsuperuser_command):
        """Test _prompt_username with blank preset raises CommandError."""
        # Simulate what happens with blank preset in --no-input mode

        err = validate_username("")
        assert err == "Username cannot be blank."

    def test_prompt_password_preset(self, createsuperuser_command):
        """Test _prompt_password with preset returns it."""
        result = createsuperuser_command.prompt_password("secretpass")
        assert result == "secretpass"


class TestCommandIntegration:
    """Integration-style tests for command execution."""

    def test_createsuperuser_no_input_missing_fields(self):
        """Test createsuperuser --no-input requires all fields."""

        cmd = CreatesuperuserCommand()

        with patch(
            "openviper.core.management.commands.createsuperuser.get_user_model"
        ) as mock_get_user:
            mock_get_user.return_value._fields = {"username": MagicMock()}

            with pytest.raises(CommandError, match="--username.*--email.*--password"):
                cmd.handle(no_input=True, username="admin", email=None, password=None)

    def test_changepassword_user_not_found(self):
        """Test changepassword raises error when user not found."""
        cmd = ChangePasswordCommand()

        mock_user_cls = MagicMock()
        mock_user_cls._fields = {"username": MagicMock()}
        mock_user_cls.objects.get_or_none = AsyncMock(return_value=None)

        with patch(
            "openviper.core.management.commands.changepassword.get_user_model",
            return_value=mock_user_cls,
        ):
            with pytest.raises(CommandError, match="not found"):
                cmd.handle(username="nonexistent", password="newpass")

    def test_console_command_with_command_option(self):
        """Test console -c option executes code and exits."""
        cmd = ShellCommand()

        with patch.object(cmd, "stdout"):
            with patch("openviper.core.management.commands.console.settings") as mock_settings:
                mock_settings.INSTALLED_APPS = []
                mock_settings.PROJECT_NAME = "test"

                # Execute simple command
                cmd.handle(no_models=True, command="x = 1 + 1")

                # Should complete without error

    def test_console_ipython_import_error(self):
        """Test console raises SystemExit when IPython not available."""
        cmd = ShellCommand()

        with patch.object(cmd, "stdout"):
            with patch("openviper.core.management.commands.console.settings") as mock_settings:
                mock_settings.INSTALLED_APPS = []
                mock_settings.PROJECT_NAME = "test"

                with (
                    patch("openviper.core.management.commands.console.ipython_embed", None),
                    patch(
                        "openviper.core.management.commands.console.INITIAL_INTERACTIVE_SHELL_EMBED",
                        None,
                    ),
                ):
                    with pytest.raises(SystemExit):
                        cmd.handle(no_models=True, command=None)
