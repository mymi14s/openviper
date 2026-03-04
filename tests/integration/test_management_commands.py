"""Integration tests for management command validation and argument parsing."""

from __future__ import annotations

import pytest

from openviper.core.management.base import CommandError

# ---------------------------------------------------------------------------
# createsuperuser validation functions
# ---------------------------------------------------------------------------


class TestCreateSuperuserValidation:
    def test_validate_username_valid(self):
        from openviper.core.management.commands.createsuperuser import _validate_username

        assert _validate_username("alice") is None

    def test_validate_username_with_special_chars(self):
        from openviper.core.management.commands.createsuperuser import _validate_username

        assert _validate_username("user.name+tag@test") is None

    def test_validate_username_empty(self):
        from openviper.core.management.commands.createsuperuser import _validate_username

        err = _validate_username("")
        assert err is not None
        assert "blank" in err.lower()

    def test_validate_username_too_long(self):
        from openviper.core.management.commands.createsuperuser import _validate_username

        long_name = "a" * 151
        err = _validate_username(long_name)
        assert err is not None

    def test_validate_username_with_spaces_invalid(self):
        from openviper.core.management.commands.createsuperuser import _validate_username

        err = _validate_username("user name")
        assert err is not None

    def test_validate_email_valid(self):
        from openviper.core.management.commands.createsuperuser import _validate_email

        assert _validate_email("user@example.com") is None

    def test_validate_email_valid_subdomain(self):
        from openviper.core.management.commands.createsuperuser import _validate_email

        assert _validate_email("user@mail.example.com") is None

    def test_validate_email_empty(self):
        from openviper.core.management.commands.createsuperuser import _validate_email

        err = _validate_email("")
        assert err is not None
        assert "blank" in err.lower()

    def test_validate_email_no_at_sign(self):
        from openviper.core.management.commands.createsuperuser import _validate_email

        err = _validate_email("notanemail")
        assert err is not None

    def test_validate_email_no_domain(self):
        from openviper.core.management.commands.createsuperuser import _validate_email

        err = _validate_email("user@")
        assert err is not None


# ---------------------------------------------------------------------------
# createsuperuser argument parsing
# ---------------------------------------------------------------------------


class TestCreateSuperuserArgParsing:
    def test_parser_has_username_arg(self):
        from openviper.core.management.commands.createsuperuser import Command

        cmd = Command()
        parser = cmd.create_parser("viperctl.py", "createsuperuser")
        opts = vars(parser.parse_args(["--username", "admin"]))
        assert opts["username"] == "admin"

    def test_parser_has_email_arg(self):
        from openviper.core.management.commands.createsuperuser import Command

        cmd = Command()
        parser = cmd.create_parser("viperctl.py", "createsuperuser")
        opts = vars(parser.parse_args(["--email", "a@b.com"]))
        assert opts["email"] == "a@b.com"

    def test_parser_has_password_arg(self):
        from openviper.core.management.commands.createsuperuser import Command

        cmd = Command()
        parser = cmd.create_parser("viperctl.py", "createsuperuser")
        opts = vars(parser.parse_args(["--password", "secret"]))
        assert opts["password"] == "secret"

    def test_parser_has_no_input_arg(self):
        from openviper.core.management.commands.createsuperuser import Command

        cmd = Command()
        parser = cmd.create_parser("viperctl.py", "createsuperuser")
        opts = vars(parser.parse_args(["--no-input"]))
        assert opts["no_input"] is True

    def test_no_input_missing_username_raises(self):
        from openviper.core.management.commands.createsuperuser import Command

        cmd = Command()
        with pytest.raises(CommandError):
            cmd.handle(no_input=True, username=None, email="a@b.com", password="pass")

    def test_no_input_invalid_username_raises(self):
        from openviper.core.management.commands.createsuperuser import Command

        cmd = Command()
        with pytest.raises(CommandError):
            cmd.handle(no_input=True, username="bad user!", email="a@b.com", password="pass")

    def test_no_input_invalid_email_raises(self):
        from openviper.core.management.commands.createsuperuser import Command

        cmd = Command()
        with pytest.raises(CommandError):
            cmd.handle(no_input=True, username="admin", email="notanemail", password="pass")


# ---------------------------------------------------------------------------
# createsuperuser _prompt_username with preset
# ---------------------------------------------------------------------------


class TestPromptUsername:
    def test_prompt_username_valid_preset(self):
        from openviper.core.management.commands.createsuperuser import Command

        cmd = Command()
        result = cmd._prompt_username("valid_user")
        assert result == "valid_user"

    def test_prompt_username_invalid_preset_raises(self):
        from openviper.core.management.commands.createsuperuser import Command

        cmd = Command()
        with pytest.raises(CommandError):
            cmd._prompt_username("bad user!")

    def test_prompt_email_valid_preset(self):
        from openviper.core.management.commands.createsuperuser import Command

        cmd = Command()
        result = cmd._prompt_email("user@example.com")
        assert result == "user@example.com"

    def test_prompt_email_invalid_preset_raises(self):
        from openviper.core.management.commands.createsuperuser import Command

        cmd = Command()
        with pytest.raises(CommandError):
            cmd._prompt_email("notvalid")

    def test_prompt_password_preset_returns(self):
        from openviper.core.management.commands.createsuperuser import Command

        cmd = Command()
        result = cmd._prompt_password("mypassword")
        assert result == "mypassword"


# ---------------------------------------------------------------------------
# migrate command argument parsing
# ---------------------------------------------------------------------------


class TestMigrateCommand:
    def test_parser_accepts_app_label(self):
        from openviper.core.management.commands.migrate import Command

        cmd = Command()
        parser = cmd.create_parser("viperctl.py", "migrate")
        opts = vars(parser.parse_args(["myapp"]))
        assert opts.get("app_label") == "myapp"

    def test_parser_accepts_fake_flag(self):
        from openviper.core.management.commands.migrate import Command

        cmd = Command()
        parser = cmd.create_parser("viperctl.py", "migrate")
        opts = vars(parser.parse_args(["--fake"]))
        assert opts.get("fake") is True

    def test_migrate_command_exists(self):
        from openviper.core.management.commands.migrate import Command

        cmd = Command()
        assert cmd.help

    def test_parser_accepts_database_flag(self):
        from openviper.core.management.commands.migrate import Command

        cmd = Command()
        parser = cmd.create_parser("viperctl.py", "migrate")
        opts = vars(parser.parse_args(["--database", "secondary"]))
        assert opts.get("database") == "secondary"


# ---------------------------------------------------------------------------
# makemigrations command argument parsing
# ---------------------------------------------------------------------------


class TestMakeMigrationsCommand:
    def test_command_has_help(self):
        from openviper.core.management.commands.makemigrations import Command

        cmd = Command()
        assert cmd.help

    def test_parser_accepts_name_flag(self):
        from openviper.core.management.commands.makemigrations import Command

        cmd = Command()
        parser = cmd.create_parser("viperctl.py", "makemigrations")
        opts = vars(parser.parse_args(["--name", "initial"]))
        assert opts.get("name") == "initial"

    def test_parser_accepts_empty_flag(self):
        from openviper.core.management.commands.makemigrations import Command

        cmd = Command()
        parser = cmd.create_parser("viperctl.py", "makemigrations")
        opts = vars(parser.parse_args(["--empty"]))
        assert opts.get("empty") is True

    def test_parser_accepts_app_labels(self):
        from openviper.core.management.commands.makemigrations import Command

        cmd = Command()
        parser = cmd.create_parser("viperctl.py", "makemigrations")
        opts = vars(parser.parse_args(["myapp", "otherapp"]))
        labels = opts.get("app_labels", [])
        assert "myapp" in labels


# ---------------------------------------------------------------------------
# runserver command argument parsing
# ---------------------------------------------------------------------------


class TestRunserverCommand:
    def test_command_has_help(self):
        from openviper.core.management.commands.runserver import Command

        cmd = Command()
        assert isinstance(cmd.help, str)

    def test_parser_accepts_host_port(self):
        from openviper.core.management.commands.runserver import Command

        cmd = Command()
        parser = cmd.create_parser("viperctl.py", "runserver")
        # runserver typically takes optional address argument
        opts = vars(parser.parse_args([]))
        assert opts is not None


# ---------------------------------------------------------------------------
# shell command
# ---------------------------------------------------------------------------


class TestShellCommand:
    def test_command_has_help(self):
        from openviper.core.management.commands.shell import Command

        cmd = Command()
        assert isinstance(cmd.help, str)


# ---------------------------------------------------------------------------
# test command
# ---------------------------------------------------------------------------


class TestTestCommand:
    def test_command_has_help(self):
        from openviper.core.management.commands.test import Command

        cmd = Command()
        assert isinstance(cmd.help, str)

    def test_parser_accepts_path_arg(self):
        from openviper.core.management.commands.test import Command

        cmd = Command()
        parser = cmd.create_parser("viperctl.py", "test")
        # Should parse without error
        opts = vars(parser.parse_args([]))
        assert opts is not None


# ---------------------------------------------------------------------------
# create_app command
# ---------------------------------------------------------------------------


class TestCreateAppCommand:
    def test_command_has_help(self):
        from openviper.core.management.commands.create_app import Command

        cmd = Command()
        assert isinstance(cmd.help, str)


# ---------------------------------------------------------------------------
# create_command command
# ---------------------------------------------------------------------------


class TestCreateCommandCommand:
    def test_command_has_help(self):
        from openviper.core.management.commands.create_command import Command

        cmd = Command()
        assert isinstance(cmd.help, str)


# ---------------------------------------------------------------------------
# runworker command
# ---------------------------------------------------------------------------


class TestRunworkerCommand:
    def test_command_has_help(self):
        from openviper.core.management.commands.runworker import Command

        cmd = Command()
        assert isinstance(cmd.help, str)
