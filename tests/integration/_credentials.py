"""Test-only credential constants for integration tests.

These values are intentionally non-production strings used solely
to exercise password hashing and verification logic.
"""

_ADMIN_PASSWORD = "t3st-adm1n-0nly"  # pragma: allowlist secret
_USER_PASSWORD = "t3st-us3r-0nly"  # pragma: allowlist secret
_EDITOR_PASSWORD = "t3st-3d1t0r-0nly"  # pragma: allowlist secret
_WRONG_PASSWORD = "t3st-wr0ng-0nly"  # pragma: allowlist secret
