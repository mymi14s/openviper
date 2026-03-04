"""Tests for create_admin.py — all branches of main() and __main__ entrypoint."""

from __future__ import annotations

import asyncio
import runpy
from unittest.mock import patch

import pytest

from tests.conftest import TODOAPP_DIR

# ── main() branches ──────────────────────────────────────────────────────────


async def test_create_new_superuser(capsys):
    """main() creates a new superuser when the username does not exist."""
    from create_admin import main

    from openviper.auth import get_user_model

    with patch("builtins.input", side_effect=["newadmin", "newadmin@example.com", "secret123"]):
        await main()

    out = capsys.readouterr().out
    assert "newadmin" in out

    User = get_user_model()
    user = await User.objects.get_or_none(username="newadmin")
    assert user is not None
    assert user.is_superuser is True
    assert user.is_staff is True


async def test_empty_password_exits_early(capsys):
    """main() prints an error and returns when password is empty."""
    from create_admin import main

    from openviper.auth import get_user_model

    with patch("builtins.input", side_effect=["nopwduser", "nopwd@example.com", ""]):
        await main()

    out = capsys.readouterr().out
    assert "cannot be empty" in out

    User = get_user_model()
    assert await User.objects.get_or_none(username="nopwduser") is None


async def test_existing_user_update_yes(capsys):
    """main() promotes an existing user when the operator answers 'y'."""
    from create_admin import main

    from openviper.auth import get_user_model

    User = get_user_model()
    existing = User(username="existingadmin", email="ex@example.com")
    existing.set_password("old_pass")
    await existing.save()

    # Inputs: username, email (ignored), password, update-prompt
    with patch("builtins.input", side_effect=["existingadmin", "", "newpass123", "y"]):
        await main()

    out = capsys.readouterr().out
    assert "Updated" in out

    updated = await User.objects.get_or_none(username="existingadmin")
    assert updated.is_superuser is True
    assert updated.is_staff is True


async def test_existing_user_update_no(capsys):
    """main() leaves an existing user unchanged when the operator declines."""
    from create_admin import main

    from openviper.auth import get_user_model

    User = get_user_model()
    existing = User(username="keepadmin", email="keep@example.com", is_superuser=False)
    existing.set_password("old_pass")
    await existing.save()

    with patch("builtins.input", side_effect=["keepadmin", "", "newpass123", "n"]):
        await main()

    out = capsys.readouterr().out
    assert "already exists" in out

    unchanged = await User.objects.get_or_none(username="keepadmin")
    assert unchanged.is_superuser is False


# ── __main__ entrypoint ───────────────────────────────────────────────────────


def test_main_entrypoint_calls_asyncio_run():
    """The if __name__ == '__main__' block calls asyncio.run(main())."""

    def _close_coro(coro):
        coro.close()  # prevent "coroutine never awaited" RuntimeWarning

    with patch.object(asyncio, "run", side_effect=_close_coro) as mock_run:
        runpy.run_path(str(TODOAPP_DIR / "create_admin.py"), run_name="__main__")
    mock_run.assert_called_once()
