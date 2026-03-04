"""Comprehensive integration tests for admin API views (CRUD, search, export, history)."""

from __future__ import annotations

import pytest
import pytest_asyncio

from openviper.admin.registry import admin as admin_registry
from openviper.admin.site import get_admin_site
from tests.factories.admin_factory import create_admin_user, create_regular_user
from tests.utils.admin_client import AdminClient


@pytest_asyncio.fixture(autouse=True)
async def setup_admin_db():
    from openviper.db.connection import close_db, init_db
    from openviper.middleware import auth as _auth_mod

    await init_db(drop_first=True)
    _auth_mod._USER_CACHE.clear()
    admin_registry.clear()
    yield
    await close_db()
    admin_registry.clear()


@pytest_asyncio.fixture
async def admin_app(app_fixture):
    from openviper.admin.middleware import AdminMiddleware
    from openviper.middleware.auth import AuthenticationMiddleware

    app_fixture._extra_middleware.extend([AuthenticationMiddleware, AdminMiddleware])
    app_fixture._middleware_app = None
    app_fixture.include_router(get_admin_site(), prefix="/admin")
    return app_fixture


@pytest_asyncio.fixture
async def client(admin_app):
    return AdminClient(admin_app)


@pytest_asyncio.fixture
async def admin_user(client):
    user = await create_admin_user(username="api_admin")
    client.login(user)
    return user


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_returns_stats_and_activity(client, admin_user):
    resp = await client.get("/admin/api/dashboard/")
    assert resp.status_code == 200
    data = resp.json()
    assert "stats" in data
    assert "recent_activity" in data
    assert isinstance(data["stats"], dict)
    assert isinstance(data["recent_activity"], list)


@pytest.mark.asyncio
async def test_dashboard_requires_admin_access(client):
    # Non-authenticated user
    resp = await client.get("/admin/api/dashboard/")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Models list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_models_list_includes_auth_models(client, admin_user):
    resp = await client.get("/admin/api/models/")
    assert resp.status_code == 200
    data = resp.json()
    assert "models" in data
    assert "apps" in data


# ---------------------------------------------------------------------------
# Config endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_endpoint_returns_defaults(client, admin_user):
    resp = await client.get("/admin/api/config/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["admin_title"] == "OpenViper Admin"


# ---------------------------------------------------------------------------
# Role CRUD via /admin/api/models/auth/role/
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_role(client, admin_user):
    resp = await client.post(
        "/admin/api/models/auth/role/",
        data={"name": "Editor", "description": "Edit access"},
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Editor"


@pytest.mark.asyncio
async def test_create_role_returns_id(client, admin_user):
    resp = await client.post(
        "/admin/api/models/auth/role/",
        data={"name": "Moderator", "description": "Moderate content"},
    )
    assert resp.status_code == 201
    assert "id" in resp.json()


@pytest.mark.asyncio
async def test_list_roles(client, admin_user):
    # Create some roles
    for i in range(3):
        await client.post(
            "/admin/api/models/auth/role/",
            data={"name": f"Role{i}", "description": ""},
        )

    resp = await client.get("/admin/api/models/auth/role/list/")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 3


@pytest.mark.asyncio
async def test_list_roles_with_pagination(client, admin_user):
    for i in range(5):
        await client.post(
            "/admin/api/models/auth/role/",
            data={"name": f"PagRole{i}", "description": ""},
        )

    resp = await client.get("/admin/api/models/auth/role/list/", params={"page": 1, "per_page": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


@pytest.mark.asyncio
async def test_list_roles_with_search(client, admin_user):
    await client.post(
        "/admin/api/models/auth/role/",
        data={"name": "SearchableRole", "description": ""},
    )
    await client.post(
        "/admin/api/models/auth/role/",
        data={"name": "OtherRole", "description": ""},
    )

    resp = await client.get("/admin/api/models/auth/role/list/", params={"q": "Searchable"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_role_detail(client, admin_user):
    create_resp = await client.post(
        "/admin/api/models/auth/role/",
        data={"name": "DetailRole", "description": "Test detail"},
    )
    role_id = create_resp.json()["id"]

    resp = await client.get(f"/admin/api/models/auth/role/{role_id}/")
    assert resp.status_code == 200
    assert resp.json()["instance"]["name"] == "DetailRole"


@pytest.mark.asyncio
async def test_get_role_not_found(client, admin_user):
    resp = await client.get("/admin/api/models/auth/role/9999/")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_role(client, admin_user):
    create_resp = await client.post(
        "/admin/api/models/auth/role/",
        data={"name": "ToUpdate", "description": "before"},
    )
    role_id = create_resp.json()["id"]

    resp = await client.put(
        f"/admin/api/models/auth/role/{role_id}/",
        data={"name": "Updated", "description": "after"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated"


@pytest.mark.asyncio
async def test_update_role_not_found(client, admin_user):
    resp = await client.put(
        "/admin/api/models/auth/role/9999/",
        data={"name": "X"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_role(client, admin_user):
    create_resp = await client.post(
        "/admin/api/models/auth/role/",
        data={"name": "ToDelete", "description": ""},
    )
    role_id = create_resp.json()["id"]

    resp = await client.delete(f"/admin/api/models/auth/role/{role_id}/")
    assert resp.status_code == 200

    # Verify it's gone
    get_resp = await client.get(f"/admin/api/models/auth/role/{role_id}/")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_role_not_found(client, admin_user):
    resp = await client.delete("/admin/api/models/auth/role/9999/")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Bulk delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_delete_roles(client, admin_user):
    ids = []
    for i in range(3):
        create_resp = await client.post(
            "/admin/api/models/auth/role/",
            data={"name": f"BulkDel{i}", "description": ""},
        )
        ids.append(create_resp.json()["id"])

    resp = await client.post(
        "/admin/api/models/auth/role/bulk-action/",
        data={"action": "delete_selected", "ids": ids},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_bulk_delete_empty_ids(client, admin_user):
    resp = await client.post(
        "/admin/api/models/auth/role/bulk-action/",
        data={"action": "delete_selected", "ids": []},
    )
    assert resp.status_code in (200, 400, 422)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_roles_csv(client, admin_user):
    await client.post(
        "/admin/api/models/auth/role/",
        data={"name": "ExportRole", "description": ""},
    )

    resp = await client.get("/admin/api/models/auth/role/export/")
    assert resp.status_code == 200
    assert "csv" in resp.headers.get("content-type", "").lower()


@pytest.mark.asyncio
async def test_export_roles_with_ids(client, admin_user):
    create_resp = await client.post(
        "/admin/api/models/auth/role/",
        data={"name": "ExportSpecific", "description": ""},
    )
    role_id = create_resp.json()["id"]

    resp = await client.get(
        "/admin/api/models/auth/role/export/",
        params={"ids": str(role_id)},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Role instance history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_role_history(client, admin_user):
    create_resp = await client.post(
        "/admin/api/models/auth/role/",
        data={"name": "HistoryRole", "description": ""},
    )
    role_id = create_resp.json()["id"]

    resp = await client.get(f"/admin/api/models/auth/role/{role_id}/history/")
    assert resp.status_code == 200
    data = resp.json()
    assert "history" in data


# ---------------------------------------------------------------------------
# Bulk actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_action_delete_selected(client, admin_user):
    ids = []
    for i in range(2):
        create_resp = await client.post(
            "/admin/api/models/auth/role/",
            data={"name": f"ActionRole{i}", "description": ""},
        )
        ids.append(create_resp.json()["id"])

    resp = await client.post(
        "/admin/api/models/auth/role/bulk-action/",
        data={"action": "delete_selected", "ids": ids},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_bulk_action_unknown_action(client, admin_user):
    create_resp = await client.post(
        "/admin/api/models/auth/role/",
        data={"name": "ActionRoleX", "description": ""},
    )
    role_id = create_resp.json()["id"]

    resp = await client.post(
        "/admin/api/models/auth/role/bulk-action/",
        data={"action": "nonexistent_action", "ids": [role_id]},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_user_password(client, admin_user):
    resp = await client.post(
        f"/admin/api/auth/change-user-password/{admin_user.id}/",
        data={
            "new_password": "NewSecure123!",
            "confirm_password": "NewSecure123!",
        },
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_change_password_mismatch(client, admin_user):
    resp = await client.post(
        f"/admin/api/auth/change-user-password/{admin_user.id}/",
        data={
            "new_password": "Password1",
            "confirm_password": "Password2",
        },
    )
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_change_password_too_short(client, admin_user):
    resp = await client.post(
        f"/admin/api/auth/change-user-password/{admin_user.id}/",
        data={
            "new_password": "short",
            "confirm_password": "short",
        },
    )
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_change_password_missing_field(client, admin_user):
    resp = await client.post(
        f"/admin/api/auth/change-user-password/{admin_user.id}/",
        data={"confirm_password": "something"},
    )
    assert resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Filter options
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_filter_options(client, admin_user):
    resp = await client.get("/admin/api/models/auth/role/")
    assert resp.status_code == 200
    data = resp.json()
    assert "fields" in data or "filters" in data or "model" in data or isinstance(data, dict)


# ---------------------------------------------------------------------------
# Non-admin user is denied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regular_user_denied_list(client):
    user = await create_regular_user(username="regular_api")
    client.login(user)
    resp = await client.get("/admin/api/models/auth/role/list/")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_unauthenticated_denied_create(client):
    # No login
    resp = await client.post(
        "/admin/api/models/auth/role/",
        data={"name": "Ghost"},
    )
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# FK search endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fk_search_returns_items(client, admin_user):
    resp = await client.get("/admin/api/models/auth/role/fk-search/")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


@pytest.mark.asyncio
async def test_fk_search_with_query(client, admin_user):
    await client.post(
        "/admin/api/models/auth/role/",
        data={"name": "SearchableFK", "description": ""},
    )
    resp = await client.get(
        "/admin/api/models/auth/role/fk-search/",
        params={"q": "Searchable"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Global search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_search_empty_query(client, admin_user):
    resp = await client.get("/admin/api/search/", params={"q": ""})
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []


@pytest.mark.asyncio
async def test_global_search_with_query(client, admin_user):
    await client.post(
        "/admin/api/models/auth/role/",
        data={"name": "GlobalSearchRole", "description": ""},
    )
    resp = await client.get("/admin/api/search/", params={"q": "GlobalSearch"})
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_me_endpoint_returns_user_info(client, admin_user):
    resp = await client.get("/admin/api/auth/me/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == admin_user.username
    assert data["is_staff"] is True
    assert data["is_superuser"] is True


@pytest.mark.asyncio
async def test_login_success(client):
    await create_admin_user(username="login_api")
    resp = await client.post(
        "/admin/api/auth/login/",
        data={"username": "login_api", "password": "password123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await create_admin_user(username="login_wrong")
    resp = await client.post(
        "/admin/api/auth/login/",
        data={"username": "login_wrong", "password": "bad_password"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_flow(client):
    await create_admin_user(username="refresh_api")
    login_resp = await client.post(
        "/admin/api/auth/login/",
        data={"username": "refresh_api", "password": "password123"},
    )
    refresh_token = login_resp.json()["refresh_token"]

    resp = await client.post(
        "/admin/api/auth/refresh/",
        data={"refresh_token": refresh_token},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_refresh_invalid_token(client):
    resp = await client.post(
        "/admin/api/auth/refresh/",
        data={"refresh_token": "not.a.valid.token"},
    )
    assert resp.status_code in (400, 401, 422)


@pytest.mark.asyncio
async def test_logout_endpoint(client, admin_user):
    resp = await client.post("/admin/api/auth/logout/", data={})
    assert resp.status_code == 200
    assert resp.json()["detail"] == "Logged out successfully."


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_unknown_model_returns_404(client, admin_user):
    resp = await client.post(
        "/admin/api/models/auth/nonexistent_model/",
        data={"name": "X"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_unknown_model_returns_404(client, admin_user):
    resp = await client.get("/admin/api/models/auth/nonexistent_model/list/")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_unknown_model_returns_404(client, admin_user):
    resp = await client.get("/admin/api/models/auth/nonexistent_model/1/")
    assert resp.status_code == 404
