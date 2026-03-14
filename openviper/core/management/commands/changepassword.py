"""changepassword management command."""

from __future__ import annotations

import argparse
import asyncio
import getpass

from openviper.auth.utils import get_user_model
from openviper.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Change a user's password."

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "username",
            nargs="?",
            default=None,
            help="Username to change password for.",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Specify the new password. If not provided, you will be prompted.",
        )

    def handle(self, **options):
        username = options.get("username")
        password = options.get("password")
        User = get_user_model()  # noqa: N806

        async def run_command():
            nonlocal username, password
            if not username:
                try:
                    username = input("Username: ").strip()
                except (EOFError, KeyboardInterrupt):
                    self.stdout("\nOperation cancelled.")
                    return

                if not username:
                    raise CommandError("Username is required.")

            field_names = set(getattr(User, "_fields", {}).keys()) or {"username"}
            if "username" in field_names:
                user = await User.objects.get_or_none(username=username)
            elif "email" in field_names:
                user = await User.objects.get_or_none(email=username)
            elif "name" in field_names:
                user = await User.objects.get_or_none(name=username)
            else:
                user = None
            if not user:
                raise CommandError(f"User '{username}' not found.")

            self.stdout(f"Changing password for user '{username}'")

            if not password:
                while True:
                    try:
                        password = getpass.getpass("New password: ")
                        if not password:
                            self.stderr(self.style_error("Password cannot be blank."))
                            continue
                        confirm = getpass.getpass("Retype new password: ")
                    except (EOFError, KeyboardInterrupt):
                        self.stdout("\nOperation cancelled.")
                        return

                    if password != confirm:
                        self.stderr(self.style_error("Passwords do not match. Try again."))
                        continue
                    break

            await user.set_password(password)
            await user.save()
            self.stdout(self.style_success(f"Password changed successfully for user '{username}'."))

        try:
            asyncio.run(run_command())
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(str(exc)) from exc
