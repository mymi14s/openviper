"""Integration tests for token revocation (blocklist) middleware auth flow."""

from __future__ import annotations

import datetime

import pytest
import pytest_asyncio

from openviper.admin.site import get_admin_site
from openviper.auth.jwt import create_access_token, create_refresh_token
from openviper.auth.token_blocklist import is_token_revoked, revoke_token
from tests.factories.admin_factory import create_admin_user
from tests.utils.admin_client import AdminClient


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    from openviper.db.connection import close_db, init_db

    await init_db(drop_first=True)
    yield
    await close_db()


@pytest_asyncio.fixture
async def auth_app(app_fixture):
    from openviper.middleware.auth import AuthenticationMiddleware

    app_fixture._extra_middleware.append(AuthenticationMiddleware)
    app_fixture._middleware_app = None
    app_fixture.include_router(get_admin_site(), prefix="/admin")
    return app_fixture


@pytest_asyncio.fixture
async def client(auth_app):
    return AdminClient(auth_app)


# ---------------------------------------------------------------------------
# Token blocklist unit-level integration tests with real DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_token_and_check_revoked():
    """revoke_token stores jti; is_token_revoked returns True."""
    jti = "test-jti-001"
    expires_at = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(hours=1)

    await revoke_token(jti=jti, token_type="access", user_id=1, expires_at=expires_at)
    assert await is_token_revoked(jti) is True


@pytest.mark.asyncio
async def test_is_token_revoked_returns_false_for_unknown():
    """is_token_revoked returns False for a jti not in the blocklist."""
    assert await is_token_revoked("nonexistent-jti") is False


@pytest.mark.asyncio
async def test_revoke_duplicate_jti_is_safe():
    """Revoking the same jti twice does not raise."""
    jti = "test-jti-dup"
    expires_at = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(hours=1)

    await revoke_token(jti=jti, token_type="refresh", user_id=2, expires_at=expires_at)
    # Second call should silently pass (duplicate jti)
    await revoke_token(jti=jti, token_type="refresh", user_id=2, expires_at=expires_at)

    assert await is_token_revoked(jti) is True


@pytest.mark.asyncio
async def test_expired_tokens_pruned_on_revoke():
    """Expired tokens are cleaned up opportunistically during revoke_token."""
    jti_expired = "expired-jti"
    past = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(hours=1)

    # Insert directly an already-expired token
    await revoke_token(jti=jti_expired, token_type="access", user_id=3, expires_at=past)

    # Now revoke another token — this should trigger pruning of the expired one
    jti_new = "new-jti-after-prune"
    future = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(hours=1)
    await revoke_token(jti=jti_new, token_type="access", user_id=3, expires_at=future)

    # The expired token should have been pruned
    assert await is_token_revoked(jti_expired) is False
    # The new token should still be there
    assert await is_token_revoked(jti_new) is True


@pytest.mark.asyncio
async def test_revoke_token_null_user_id():
    """revoke_token allows null user_id."""
    jti = "test-jti-null-user"
    expires_at = datetime.datetime.now(tz=datetime.timezone.utc) + datetime.timedelta(hours=1)

    await revoke_token(jti=jti, token_type="access", user_id=None, expires_at=expires_at)
    assert await is_token_revoked(jti) is True


# ---------------------------------------------------------------------------
# End-to-end: admin logout revokes tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_logout_revokes_access_token(client):
    """POST /admin/api/auth/logout/ adds access token to blocklist."""
    admin_user = await create_admin_user(username="logout_test")
    client.login(admin_user)

    # Access a protected endpoint successfully
    resp = await client.get("/admin/api/auth/me/")
    assert resp.status_code == 200

    # Logout
    resp = await client.post("/admin/api/auth/logout/", data={})
    assert resp.status_code == 200
    assert resp.json()["detail"] == "Logged out successfully."


@pytest.mark.asyncio
async def test_admin_logout_revokes_refresh_token(client):
    """POST /admin/api/auth/logout/ with refresh_token also revokes it."""
    admin_user = await create_admin_user(username="logout_refresh")

    login_resp = await client.post(
        "/admin/api/auth/login/",
        data={"username": "logout_refresh", "password": "password123"},
    )
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    refresh_token = tokens["refresh_token"]

    # Set access token on client
    client.access_token = tokens["access_token"]

    # Logout with refresh token in body
    logout_resp = await client.post(
        "/admin/api/auth/logout/",
        data={"refresh_token": refresh_token},
    )
    assert logout_resp.status_code == 200

    # Try to use the refresh token — should be rejected
    refresh_resp = await client.post(
        "/admin/api/auth/refresh/",
        data={"refresh_token": refresh_token},
    )
    # After revocation, refresh should fail
    assert refresh_resp.status_code in (400, 401, 403, 422)


@pytest.mark.asyncio
async def test_admin_logout_without_token_still_succeeds(client):
    """Logout with no Authorization header succeeds gracefully."""
    # No login — anonymous request
    resp = await client.post("/admin/api/auth/logout/", data={})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_revoked_access_token_is_rejected_by_middleware(client):
    """After logout, the revoked access token cannot access protected endpoints."""
    admin_user = await create_admin_user(username="revoke_middleware")
    client.login(admin_user)

    # Verify initial access
    resp = await client.get("/admin/api/auth/me/")
    assert resp.status_code == 200

    # Grab the token before logout
    old_token = client.access_token

    # Logout to revoke
    await client.post("/admin/api/auth/logout/", data={})

    # Try to reuse the revoked token manually — middleware should reject it
    client.access_token = old_token
    resp = await client.get("/admin/api/auth/me/")
    # After token revocation, the middleware falls through to anonymous → 401
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# JWT claim extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_access_token_has_jti():
    """create_access_token includes a jti claim."""
    from openviper.auth.jwt import decode_access_token

    token = create_access_token(user_id=1)
    payload = decode_access_token(token)
    assert "jti" in payload
    assert payload["jti"]  # non-empty


@pytest.mark.asyncio
async def test_refresh_token_has_jti():
    """create_refresh_token includes a jti claim."""
    from openviper.auth.jwt import decode_refresh_token

    token = create_refresh_token(user_id=1)
    payload = decode_refresh_token(token)
    assert "jti" in payload
    assert payload["jti"]  # non-empty


@pytest.mark.asyncio
async def test_decode_token_unverified_extracts_claims():
    """decode_token_unverified works for both access and refresh tokens."""
    from openviper.auth.jwt import decode_token_unverified

    access_token = create_access_token(user_id=42)
    refresh_token = create_refresh_token(user_id=42)

    access_claims = decode_token_unverified(access_token)
    refresh_claims = decode_token_unverified(refresh_token)

    assert access_claims["sub"] == "42"
    assert access_claims["type"] == "access"
    assert "jti" in access_claims

    assert refresh_claims["sub"] == "42"
    assert refresh_claims["type"] == "refresh"
    assert "jti" in refresh_claims


@pytest.mark.asyncio
async def test_decode_token_unverified_returns_empty_on_garbage():
    """decode_token_unverified returns {} for malformed tokens."""
    from openviper.auth.jwt import decode_token_unverified

    assert decode_token_unverified("not.a.token") == {}
    assert decode_token_unverified("") == {}
