"""Unit tests for the createsuperuser management command."""

from __future__ import annotations

import argparse
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.core.management.base import CommandError
from openviper.core.management.commands.createsuperuser import (
    Command,
    _validate_email,
    _validate_username,
)

# ---------------------------------------------------------------------------
# Helper: run a coroutine in a fresh event loop (avoids conflicts with pytest)
# ---------------------------------------------------------------------------


def _make_async_runner():
    """Return a side_effect function that actually executes the coroutine."""

    def runner(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    return runner


# ---------------------------------------------------------------------------
# _validate_username tests
# ---------------------------------------------------------------------------


def test_validate_username_blank():
    assert _validate_username("") == "Username cannot be blank."


def test_validate_username_invalid_chars():
    err = _validate_username("bad username!")
    assert err is not None
    assert "Invalid username" in err


def test_validate_username_too_long():
    long_name = "a" * 151
    err = _validate_username(long_name)
    assert err is not None


def test_validate_username_valid_plain():
    assert _validate_username("admin") is None


def test_validate_username_valid_with_specials():
    assert _validate_username("user.name+test@me") is None
    assert _validate_username("user-123") is None


def test_validate_username_max_length():
    assert _validate_username("u" * 150) is None  # exactly 150


# ---------------------------------------------------------------------------
# _validate_email tests
# ---------------------------------------------------------------------------


def test_validate_email_blank():
    assert _validate_email("") == "Email cannot be blank."


def test_validate_email_missing_at():
    assert _validate_email("notanemail") == "Enter a valid email address."


def test_validate_email_missing_tld():
    assert _validate_email("user@domain") == "Enter a valid email address."


def test_validate_email_empty_local():
    assert _validate_email("@domain.com") == "Enter a valid email address."


def test_validate_email_valid_simple():
    assert _validate_email("user@example.com") is None


def test_validate_email_valid_complex():
    assert _validate_email("a.b+c@d.co.uk") is None


# ---------------------------------------------------------------------------
# _prompt_username tests
# ---------------------------------------------------------------------------


class TestPromptUsername:
    def test_preset_valid_returns_immediately(self):
        cmd = Command()
        assert cmd._prompt_username("validuser") == "validuser"

    def test_preset_invalid_raises_command_error(self):
        cmd = Command()
        with pytest.raises(CommandError, match="Invalid username"):
            cmd._prompt_username("bad user!")

    def test_preset_blank_enters_interactive_mode(self):
        """Empty string is falsy, so it falls through to the interactive input loop."""
        cmd = Command()
        with patch("builtins.input", return_value="validuser"):
            result = cmd._prompt_username("")
        assert result == "validuser"

    def test_interactive_first_try_valid(self):
        cmd = Command()
        with patch("builtins.input", return_value="myuser"):
            assert cmd._prompt_username(None) == "myuser"

    def test_interactive_strips_whitespace(self):
        cmd = Command()
        with patch("builtins.input", return_value="  myuser  "):
            assert cmd._prompt_username(None) == "myuser"

    def test_interactive_retries_on_blank_then_valid(self):
        cmd = Command()
        inputs = iter(["", "validuser"])
        with (
            patch("builtins.input", side_effect=lambda _: next(inputs)),
            patch.object(cmd, "stderr"),
        ):
            result = cmd._prompt_username(None)
        assert result == "validuser"

    def test_interactive_retries_on_invalid_chars(self):
        cmd = Command()
        inputs = iter(["bad user!", "gooduser"])
        with (
            patch("builtins.input", side_effect=lambda _: next(inputs)),
            patch.object(cmd, "stderr"),
        ):
            result = cmd._prompt_username(None)
        assert result == "gooduser"


# ---------------------------------------------------------------------------
# _prompt_email tests
# ---------------------------------------------------------------------------


class TestPromptEmail:
    def test_preset_valid_returns_immediately(self):
        cmd = Command()
        assert cmd._prompt_email("user@example.com") == "user@example.com"

    def test_preset_invalid_raises_command_error(self):
        cmd = Command()
        with pytest.raises(CommandError, match="valid email"):
            cmd._prompt_email("notvalid")

    def test_preset_blank_enters_interactive_mode(self):
        """Empty string is falsy, so it falls through to the interactive input loop."""
        cmd = Command()
        with patch("builtins.input", return_value="user@example.com"):
            result = cmd._prompt_email("")
        assert result == "user@example.com"

    def test_interactive_first_try_valid(self):
        cmd = Command()
        with patch("builtins.input", return_value="user@example.com"):
            assert cmd._prompt_email(None) == "user@example.com"

    def test_interactive_retries_on_invalid(self):
        cmd = Command()
        inputs = iter(["bademail", "user@example.com"])
        with (
            patch("builtins.input", side_effect=lambda _: next(inputs)),
            patch.object(cmd, "stderr"),
        ):
            result = cmd._prompt_email(None)
        assert result == "user@example.com"


# ---------------------------------------------------------------------------
# _prompt_password tests
# ---------------------------------------------------------------------------


class TestPromptPassword:
    def test_preset_returned_directly(self):
        cmd = Command()
        assert cmd._prompt_password("secret123") == "secret123"

    def test_interactive_success_on_first_try(self):
        cmd = Command()
        with patch("getpass.getpass", side_effect=["secret", "secret"]):
            assert cmd._prompt_password(None) == "secret"

    def test_interactive_blank_then_valid(self):
        cmd = Command()
        # blank password -> retry -> valid pair
        with (
            patch("getpass.getpass", side_effect=["", "password1", "password1"]),
            patch.object(cmd, "stderr"),
        ):
            result = cmd._prompt_password(None)
        assert result == "password1"

    def test_interactive_mismatch_then_valid(self):
        cmd = Command()
        with (
            patch("getpass.getpass", side_effect=["pass1", "wrongpass", "pass1", "pass1"]),
            patch.object(cmd, "stderr"),
        ):
            result = cmd._prompt_password(None)
        assert result == "pass1"


# ---------------------------------------------------------------------------
# handle() – no_input mode
# ---------------------------------------------------------------------------


class TestHandleNoInput:
    def _make_user_class(self):
        User = MagicMock()
        mock_user = MagicMock()
        mock_user.save = AsyncMock()
        User.objects.get_or_none = AsyncMock(return_value=None)
        User.objects.create = AsyncMock(return_value=mock_user)
        return User, mock_user

    def test_missing_all_required_fields(self):
        cmd = Command()
        with (
            patch(
                "openviper.core.management.commands.createsuperuser.get_user_model",
                return_value=MagicMock(),
            ),
            pytest.raises(CommandError, match="required with --no-input"),
        ):
            cmd.handle(no_input=True, username=None, email=None, password=None)

    def test_missing_email_raises(self):
        cmd = Command()
        with (
            patch(
                "openviper.core.management.commands.createsuperuser.get_user_model",
                return_value=MagicMock(),
            ),
            pytest.raises(CommandError, match="required with --no-input"),
        ):
            cmd.handle(no_input=True, username="admin", email=None, password="pw")

    def test_missing_password_raises(self):
        cmd = Command()
        with (
            patch(
                "openviper.core.management.commands.createsuperuser.get_user_model",
                return_value=MagicMock(),
            ),
            pytest.raises(CommandError, match="required with --no-input"),
        ):
            cmd.handle(no_input=True, username="admin", email="a@b.com", password=None)

    def test_invalid_username_raises(self):
        cmd = Command()
        with (
            patch(
                "openviper.core.management.commands.createsuperuser.get_user_model",
                return_value=MagicMock(),
            ),
            pytest.raises(CommandError, match="Invalid username"),
        ):
            cmd.handle(
                no_input=True,
                username="bad user!",
                email="a@b.com",
                password="pw",
            )

    def test_invalid_email_raises(self):
        cmd = Command()
        with (
            patch(
                "openviper.core.management.commands.createsuperuser.get_user_model",
                return_value=MagicMock(),
            ),
            pytest.raises(CommandError, match="valid email"),
        ):
            cmd.handle(
                no_input=True,
                username="admin",
                email="notvalidemail",
                password="pw",
            )

    def test_existing_username_raises(self):
        cmd = Command()
        User, _ = self._make_user_class()
        User.objects.get_or_none = AsyncMock(return_value=MagicMock())  # user exists
        with (
            patch(
                "openviper.core.management.commands.createsuperuser.get_user_model",
                return_value=User,
            ),
            patch(
                "openviper.core.management.commands.createsuperuser.asyncio.run",
                side_effect=_make_async_runner(),
            ),
            pytest.raises(CommandError, match="already exists"),
        ):
            cmd.handle(
                no_input=True,
                username="admin",
                email="a@b.com",
                password="pw",
            )

    def test_existing_email_raises(self):
        cmd = Command()
        User, _ = self._make_user_class()
        # First call (username check) returns None; second call (email check) returns existing user
        User.objects.get_or_none = AsyncMock(side_effect=[None, MagicMock()])
        with (
            patch(
                "openviper.core.management.commands.createsuperuser.get_user_model",
                return_value=User,
            ),
            patch(
                "openviper.core.management.commands.createsuperuser.asyncio.run",
                side_effect=_make_async_runner(),
            ),
            pytest.raises(CommandError, match="already exists"),
        ):
            cmd.handle(
                no_input=True,
                username="admin",
                email="admin@example.com",
                password="pw",
            )

    def test_success_creates_superuser(self):
        cmd = Command()
        User, mock_user = self._make_user_class()
        with (
            patch(
                "openviper.core.management.commands.createsuperuser.get_user_model",
                return_value=User,
            ),
            patch(
                "openviper.core.management.commands.createsuperuser.asyncio.run",
                side_effect=_make_async_runner(),
            ),
        ):
            cmd.handle(
                no_input=True,
                username="admin",
                email="admin@example.com",
                password="secret123",
            )

        User.objects.create.assert_awaited_once_with(
            username="admin",
            email="admin@example.com",
            is_superuser=True,
            is_staff=True,
            is_active=True,
        )
        mock_user.set_password.assert_called_once_with("secret123")
        mock_user.save.assert_awaited_once()

    def test_success_outputs_success_message(self):
        cmd = Command()
        User, mock_user = self._make_user_class()
        output_lines = []
        with (
            patch(
                "openviper.core.management.commands.createsuperuser.get_user_model",
                return_value=User,
            ),
            patch(
                "openviper.core.management.commands.createsuperuser.asyncio.run",
                side_effect=_make_async_runner(),
            ),
            patch.object(cmd, "stdout", side_effect=lambda msg: output_lines.append(msg)),
        ):
            cmd.handle(
                no_input=True,
                username="admin",
                email="admin@example.com",
                password="pw",
            )

        assert any("admin" in line for line in output_lines)


# ---------------------------------------------------------------------------
# handle() – interactive mode
# ---------------------------------------------------------------------------


class TestHandleInteractive:
    def test_interactive_delegates_to_prompt_helpers(self):
        cmd = Command()
        User = MagicMock()
        User.objects.get_or_none = AsyncMock(return_value=None)
        mock_user = MagicMock()
        mock_user.save = AsyncMock()
        User.objects.create = AsyncMock(return_value=mock_user)

        with patch(
            "openviper.core.management.commands.createsuperuser.get_user_model",
            return_value=User,
        ):
            with (
                patch.object(cmd, "_prompt_username", return_value="newuser") as mu,
                patch.object(cmd, "_prompt_email", return_value="new@example.com") as me,
                patch.object(cmd, "_prompt_password", return_value="mypassword") as mp,
                patch(
                    "openviper.core.management.commands.createsuperuser.asyncio.run",
                    side_effect=_make_async_runner(),
                ),
            ):
                cmd.handle(
                    no_input=False,
                    username=None,
                    email=None,
                    password=None,
                )
            mu.assert_called_once_with(None)
            me.assert_called_once_with(None)
            mp.assert_called_once_with(None)

        User.objects.create.assert_awaited_once()
        mock_user.save.assert_awaited_once()

    def test_interactive_passes_preset_values_to_prompts(self):
        cmd = Command()
        User = MagicMock()
        User.objects.get_or_none = AsyncMock(return_value=None)
        mock_user = MagicMock()
        mock_user.save = AsyncMock()
        User.objects.create = AsyncMock(return_value=mock_user)

        with patch(
            "openviper.core.management.commands.createsuperuser.get_user_model",
            return_value=User,
        ):
            with (
                patch.object(cmd, "_prompt_username", return_value="preset") as mu,
                patch.object(cmd, "_prompt_email", return_value="p@e.com") as me,
                patch.object(cmd, "_prompt_password", return_value="pw") as mp,
                patch(
                    "openviper.core.management.commands.createsuperuser.asyncio.run",
                    side_effect=_make_async_runner(),
                ),
            ):
                cmd.handle(
                    no_input=False,
                    username="preset",
                    email="p@e.com",
                    password="pw",
                )
            mu.assert_called_once_with("preset")
            me.assert_called_once_with("p@e.com")
            mp.assert_called_once_with("pw")


# ---------------------------------------------------------------------------
# add_arguments
# ---------------------------------------------------------------------------


def test_add_arguments():

    cmd = Command()
    parser = argparse.ArgumentParser()
    cmd.add_arguments(parser)

    args = parser.parse_args(
        ["--username", "admin", "--email", "a@b.com", "--password", "secret", "--no-input"]
    )
    assert args.username == "admin"
    assert args.email == "a@b.com"
    assert args.password == "secret"
    assert args.no_input is True
