"""Test-only credential helpers for integration tests.

Passwords are generated fresh at process start using the secrets module so no
static credential strings appear in source code or revision history.
"""

import secrets

_ADMIN_PASSWORD: str = secrets.token_urlsafe(32)
_USER_PASSWORD: str = secrets.token_urlsafe(32)
_EDITOR_PASSWORD: str = secrets.token_urlsafe(32)
_WRONG_PASSWORD: str = secrets.token_urlsafe(32)
