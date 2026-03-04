"""Unit tests for the changepassword management command."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.core.management.base import CommandError
from openviper.core.management.commands.changepassword import Command

# ---------------------------------------------------------------------------
# Helper: run a coroutine in a fresh event loop
# ---------------------------------------------------------------------------


def _make_async_runner():
    def runner(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    return runner


# ---------------------------------------------------------------------------
# Helpers to build User mocks
# ---------------------------------------------------------------------------


def _user_found(password_change_ok=True):
    User = MagicMock()
    mock_user = MagicMock()
    mock_user.save = AsyncMock()
    User.objects.get_or_none = AsyncMock(return_value=mock_user)
    return User, mock_user


def _user_not_found():
    User = MagicMock()
    User.objects.get_or_none = AsyncMock(return_value=None)
    return User


# ---------------------------------------------------------------------------
# add_arguments
# ---------------------------------------------------------------------------


def test_add_arguments_parses_positional_and_flag():
    import argparse

    cmd = Command()
    parser = argparse.ArgumentParser()
    cmd.add_arguments(parser)

    args = parser.parse_args(["admin", "--password", "newpass"])
    assert args.username == "admin"
    assert args.password == "newpass"


def test_add_arguments_defaults_are_none():
    import argparse

    cmd = Command()
    parser = argparse.ArgumentParser()
    cmd.add_arguments(parser)

    args = parser.parse_args([])
    assert args.username is None
    assert args.password is None


# ---------------------------------------------------------------------------
# handle – username provided via options
# ---------------------------------------------------------------------------


class TestHandleUsernameFromOptions:
    def test_user_not_found_raises(self):
        cmd = Command()
        User = _user_not_found()
        with patch(
            "openviper.core.management.commands.changepassword.get_user_model",
            return_value=User,
        ):
            with patch(
                "openviper.core.management.commands.changepassword.asyncio.run",
                side_effect=_make_async_runner(),
            ):
                with pytest.raises(CommandError, match="not found"):
                    cmd.handle(username="nonexistent", password=None)

    def test_password_from_option_skips_prompt(self):
        cmd = Command()
        User, mock_user = _user_found()
        with patch(
            "openviper.core.management.commands.changepassword.get_user_model",
            return_value=User,
        ):
            with patch(
                "openviper.core.management.commands.changepassword.asyncio.run",
                side_effect=_make_async_runner(),
            ):
                cmd.handle(username="admin", password="directpass")

        mock_user.set_password.assert_called_once_with("directpass")
        mock_user.save.assert_awaited_once()

    def test_outputs_changing_message(self):
        cmd = Command()
        User, mock_user = _user_found()
        messages = []
        with patch(
            "openviper.core.management.commands.changepassword.get_user_model",
            return_value=User,
        ):
            with patch(
                "openviper.core.management.commands.changepassword.asyncio.run",
                side_effect=_make_async_runner(),
            ):
                with patch.object(cmd, "stdout", side_effect=lambda m: messages.append(m)):
                    cmd.handle(username="admin", password="pw")

        assert any("admin" in m for m in messages)


# ---------------------------------------------------------------------------
# handle – username prompted interactively
# ---------------------------------------------------------------------------


class TestHandleUsernamePrompted:
    def test_eoferror_during_username_prompt_cancels(self):
        cmd = Command()
        User, _ = _user_found()
        with patch(
            "openviper.core.management.commands.changepassword.get_user_model",
            return_value=User,
        ):
            with patch(
                "openviper.core.management.commands.changepassword.asyncio.run",
                side_effect=_make_async_runner(),
            ):
                with patch("builtins.input", side_effect=EOFError):
                    stdout_calls = []
                    with patch.object(cmd, "stdout", side_effect=lambda m: stdout_calls.append(m)):
                        cmd.handle(username=None, password=None)
                    assert any("cancelled" in m.lower() for m in stdout_calls)

    def test_keyboard_interrupt_during_username_prompt_cancels(self):
        cmd = Command()
        User, _ = _user_found()
        with patch(
            "openviper.core.management.commands.changepassword.get_user_model",
            return_value=User,
        ):
            with patch(
                "openviper.core.management.commands.changepassword.asyncio.run",
                side_effect=_make_async_runner(),
            ):
                with patch("builtins.input", side_effect=KeyboardInterrupt):
                    stdout_calls = []
                    with patch.object(cmd, "stdout", side_effect=lambda m: stdout_calls.append(m)):
                        cmd.handle(username=None, password=None)
                    assert any("cancelled" in m.lower() for m in stdout_calls)

    def test_empty_username_raises_command_error(self):
        cmd = Command()
        User, _ = _user_found()
        with patch(
            "openviper.core.management.commands.changepassword.get_user_model",
            return_value=User,
        ):
            with patch(
                "openviper.core.management.commands.changepassword.asyncio.run",
                side_effect=_make_async_runner(),
            ):
                # input returns spaces only -> stripped to empty string
                with patch("builtins.input", return_value="   "):
                    with pytest.raises(CommandError, match="Username is required"):
                        cmd.handle(username=None, password=None)

    def test_valid_username_from_prompt_proceeds_to_password(self):
        cmd = Command()
        User, mock_user = _user_found()
        with patch(
            "openviper.core.management.commands.changepassword.get_user_model",
            return_value=User,
        ):
            with patch(
                "openviper.core.management.commands.changepassword.asyncio.run",
                side_effect=_make_async_runner(),
            ):
                with patch("builtins.input", return_value="admin"):
                    with patch("getpass.getpass", side_effect=["newpass", "newpass"]):
                        cmd.handle(username=None, password=None)

        mock_user.set_password.assert_called_once_with("newpass")
        mock_user.save.assert_awaited_once()


# ---------------------------------------------------------------------------
# handle – interactive password flow
# ---------------------------------------------------------------------------


class TestHandlePasswordInteractive:
    def test_blank_password_retries(self):
        cmd = Command()
        User, mock_user = _user_found()
        with patch(
            "openviper.core.management.commands.changepassword.get_user_model",
            return_value=User,
        ):
            with patch(
                "openviper.core.management.commands.changepassword.asyncio.run",
                side_effect=_make_async_runner(),
            ):
                # First attempt blank, second attempt successful
                with patch("getpass.getpass", side_effect=["", "mypass", "mypass"]):
                    with patch.object(cmd, "stderr"):
                        cmd.handle(username="admin", password=None)

        mock_user.set_password.assert_called_once_with("mypass")

    def test_password_mismatch_retries(self):
        cmd = Command()
        User, mock_user = _user_found()
        with patch(
            "openviper.core.management.commands.changepassword.get_user_model",
            return_value=User,
        ):
            with patch(
                "openviper.core.management.commands.changepassword.asyncio.run",
                side_effect=_make_async_runner(),
            ):
                with patch(
                    "getpass.getpass",
                    side_effect=["pass1", "wrongpass", "pass1", "pass1"],
                ):
                    with patch.object(cmd, "stderr"):
                        cmd.handle(username="admin", password=None)

        mock_user.set_password.assert_called_once_with("pass1")

    def test_eoferror_during_password_prompt_cancels(self):
        cmd = Command()
        User, mock_user = _user_found()
        with patch(
            "openviper.core.management.commands.changepassword.get_user_model",
            return_value=User,
        ):
            with patch(
                "openviper.core.management.commands.changepassword.asyncio.run",
                side_effect=_make_async_runner(),
            ):
                with patch("getpass.getpass", side_effect=EOFError):
                    stdout_calls = []
                    with patch.object(cmd, "stdout", side_effect=lambda m: stdout_calls.append(m)):
                        cmd.handle(username="admin", password=None)
                    assert any("cancelled" in m.lower() for m in stdout_calls)
        # save should NOT have been called since we cancelled
        mock_user.save.assert_not_awaited()

    def test_keyboard_interrupt_during_password_cancels(self):
        cmd = Command()
        User, mock_user = _user_found()
        with patch(
            "openviper.core.management.commands.changepassword.get_user_model",
            return_value=User,
        ):
            with patch(
                "openviper.core.management.commands.changepassword.asyncio.run",
                side_effect=_make_async_runner(),
            ):
                with patch("getpass.getpass", side_effect=KeyboardInterrupt):
                    stdout_calls = []
                    with patch.object(cmd, "stdout", side_effect=lambda m: stdout_calls.append(m)):
                        cmd.handle(username="admin", password=None)
                    assert any("cancelled" in m.lower() for m in stdout_calls)
        mock_user.save.assert_not_awaited()

    def test_success_outputs_success_message(self):
        cmd = Command()
        User, mock_user = _user_found()
        stdout_calls = []
        with patch(
            "openviper.core.management.commands.changepassword.get_user_model",
            return_value=User,
        ):
            with patch(
                "openviper.core.management.commands.changepassword.asyncio.run",
                side_effect=_make_async_runner(),
            ):
                with patch("getpass.getpass", side_effect=["goodpass", "goodpass"]):
                    with patch.object(cmd, "stdout", side_effect=lambda m: stdout_calls.append(m)):
                        cmd.handle(username="admin", password=None)

        assert any("successfully" in m.lower() or "admin" in m for m in stdout_calls)
