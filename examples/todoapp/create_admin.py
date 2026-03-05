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

import openviper  # noqa: E402

openviper.setup(force=True)

from openviper.auth import get_user_model  # noqa: E402
from openviper.db import init_db  # noqa: E402


async def main() -> None:
    await init_db()

    User = get_user_model()  # noqa: N806

    username = input("Username [admin]: ").strip() or "admin"
    email = input("Email: ").strip()
    password = input("Password: ").strip()

    if not password:
        print("Password cannot be empty.")
        return

    existing = await User.objects.get_or_none(username=username)
    if existing is not None:
        print(f"User '{username}' already exists.")
        update = input("Update password and set as superuser? [y/N]: ").strip().lower()
        if update == "y":
            existing.set_password(password)
            existing.is_superuser = True
            existing.is_staff = True
            await existing.save()
            print(f"Updated '{username}'.")
        return

    user = User(username=username, email=email, is_superuser=True, is_staff=True)
    user.set_password(password)
    await user.save()
    print(f"Superuser '{username}' created.")


if __name__ == "__main__":
    asyncio.run(main())
