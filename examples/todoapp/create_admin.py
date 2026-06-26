"""Create an admin (superuser) account.

Usage::
python create_admin.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OPENVIPER_SETTINGS_MODULE", "settings")

import openviper

openviper.setup(force=True)

from openviper.auth import get_user_model
from openviper.db import init_db


async def prompt_text(prompt: str) -> str:
    return (await asyncio.to_thread(input, prompt)).strip()


async def main() -> None:
    await init_db()

    user_model = get_user_model()

    username = await prompt_text("Username [admin]: ") or "admin"
    email = await prompt_text("Email: ")
    password = await prompt_text("Password: ")

    if not password:
        print("Password cannot be empty.")
        return

    existing = await user_model.objects.get_or_none(username=username)
    if existing is not None:
        print(f"User '{username}' already exists.")
        update = (await prompt_text("Update password and set as superuser? [y/N]: ")).lower()
        if update == "y":
            await existing.set_password(password)
            existing.is_superuser = True
            existing.is_staff = True
            await existing.save()
            print(f"Updated '{username}'.")
        return

    user = user_model(username=username, email=email, is_superuser=True, is_staff=True)
    await user.set_password(password)
    await user.save()
    print(f"Superuser '{username}' created.")


if __name__ == "__main__":
    asyncio.run(main())
