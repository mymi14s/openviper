"""Test-only credential helpers for integration tests.

Passwords are generated fresh at process start using the secrets module so no
static credential strings appear in source code or revision history.
"""

import secrets

ADMIN_PASSWORD: str = secrets.token_urlsafe(32)
USER_PASSWORD: str = secrets.token_urlsafe(32)
EDITOR_PASSWORD: str = secrets.token_urlsafe(32)
WRONG_PASSWORD: str = secrets.token_urlsafe(32)
