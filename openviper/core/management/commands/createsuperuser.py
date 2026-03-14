"""createsuperuser management command."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import re

from openviper.auth.utils import get_user_model
from openviper.core.management.base import BaseCommand, CommandError

# Username: letters, digits, underscores, hyphens, dots — 1-150 chars.
_USERNAME_RE = re.compile(r"^[\w.@+-]{1,150}$")
# Simplified RFC-5322-ish check — good enough for interactive prompts.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_username(value: str) -> str | None:
    """Return an error message if *value* is not a valid username, else None."""
    if not value:
        return "Username cannot be blank."
    if not _USERNAME_RE.match(value):
        return (
            "Invalid username. Use only letters, digits, and @/./+/-/_ characters "
            "(1-150 characters)."
        )
    return None


def _validate_email(value: str) -> str | None:
    """Return an error message if *value* is not a valid email, else None."""
    if not value:
        return "Email cannot be blank."
    if not _EMAIL_RE.match(value):
        return "Enter a valid email address."
    return None


def _model_field_names(user_model: type) -> set[str]:
    """Return declared field names for *user_model*.

    Falls back to the built-in auth contract when model metadata is unavailable,
    which keeps the command tests and simple mock models working.
    """
    fields = getattr(user_model, "_fields", None)
    if isinstance(fields, dict) and fields:
        return set(fields)
    return {"username", "email", "is_superuser", "is_staff", "is_active"}


def _build_user_kwargs(field_names: set[str], username: str, email: str) -> dict[str, object]:
    """Build constructor kwargs compatible with the selected user model."""
    kwargs: dict[str, object] = {}

    if "username" in field_names:
        kwargs["username"] = username
    if "email" in field_names:
        kwargs["email"] = email
    if "name" in field_names:
        kwargs["name"] = username

    for field_name in ("is_superuser", "is_staff", "is_active"):
        if field_name in field_names:
            kwargs[field_name] = True

    return kwargs


class Command(BaseCommand):
    help = "Create a superuser account interactively."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--username", default=None)
        parser.add_argument("--email", default=None)
        parser.add_argument("--password", default=None, help="NOT RECOMMENDED for production use")
        parser.add_argument("--no-input", action="store_true", help="Skip interactive prompts")

    # ── helpers ────────────────────────────────────────────────────────

    def _prompt_username(self, preset: str | None) -> str:
        """Prompt until a syntactically valid username is entered."""
        if preset:
            err = _validate_username(preset)
            if err:
                raise CommandError(err)
            return preset
        while True:
            value = input("Username: ").strip()
            err = _validate_username(value)
            if err:
                self.stderr(self.style_error(err))
                continue
            return value

    def _prompt_email(self, preset: str | None) -> str:
        """Prompt until a syntactically valid email is entered."""
        if preset:
            err = _validate_email(preset)
            if err:
                raise CommandError(err)
            return preset
        while True:
            value = input("Email address: ").strip()
            err = _validate_email(value)
            if err:
                self.stderr(self.style_error(err))
                continue
            return value

    def _prompt_password(self, preset: str | None) -> str:
        """Prompt for matching password pair."""
        if preset:
            return preset
        while True:
            password = getpass.getpass("Password: ")
            if not password:
                self.stderr(self.style_error("Password cannot be blank."))
                continue
            confirm = getpass.getpass("Password (again): ")
            if password != confirm:
                self.stderr(self.style_error("Passwords do not match. Try again."))
                continue
            return password

    # ── main handler ──────────────────────────────────────────────────

    def handle(self, **options):  # type: ignore[override]

        User = get_user_model()  # noqa: N806
        field_names = _model_field_names(User)

        no_input = options.get("no_input", False)

        if no_input:
            username = options.get("username")
            email = options.get("email")
            password = options.get("password")
            if not username or not email or not password:
                raise CommandError(
                    "--username, --email, and --password are required with --no-input."
                )
            err = _validate_username(username)
            if err:
                raise CommandError(err)
            err = _validate_email(email)
            if err:
                raise CommandError(err)
        else:
            username = self._prompt_username(options.get("username"))
            email = self._prompt_email(options.get("email"))
            password = self._prompt_password(options.get("password"))

        async def create() -> None:
            # Check for existing user with the same username or email
            username_lookup = None
            if "username" in field_names:
                username_lookup = "username"
            elif "name" in field_names:
                username_lookup = "name"

            if username_lookup is not None:
                existing = await User.objects.get_or_none(**{username_lookup: username})
                if existing is not None:
                    raise CommandError(
                        f"A user with {username_lookup} '{username}' already exists."
                    )

            if "email" in field_names:
                existing = await User.objects.get_or_none(email=email)
                if existing is not None:
                    raise CommandError(f"A user with email '{email}' already exists.")

            missing_admin_fields = [
                field_name
                for field_name in ("is_superuser", "is_staff")
                if field_name not in field_names
            ]
            if missing_admin_fields:
                self.stderr(
                    self.style_warning(
                        "Custom user model is missing admin flags "
                        + ", ".join(missing_admin_fields)
                        + "; the created account will not have persisted admin privileges."
                    )
                )

            user = User(**_build_user_kwargs(field_names, username, email))
            await user.set_password(password)
            await user.save()
            self.stdout(self.style_success(f"Superuser '{username}' created successfully."))

        try:
            asyncio.run(create())
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(str(exc)) from exc
