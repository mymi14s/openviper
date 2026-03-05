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
            existing = await User.objects.get_or_none(username=username)
            if existing is not None:
                raise CommandError(f"A user with username '{username}' already exists.")

            existing = await User.objects.get_or_none(email=email)
            if existing is not None:
                raise CommandError(f"A user with email '{email}' already exists.")

            user = await User.objects.create(
                username=username,
                email=email,
                is_superuser=True,
                is_staff=True,
                is_active=True,
            )
            user.set_password(password)
            await user.save()
            self.stdout(self.style_success(f"Superuser '{username}' created successfully."))

        asyncio.run(create())
