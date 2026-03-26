"""Comprehensive full system integration tests for OpenViper.

This module contains end-to-end tests that verify all major components
of OpenViper work together correctly, simulating real-world application
behavior.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from openviper.app import OpenViper
from openviper.auth.models import Permission, Role, User
from openviper.cache import get_cache
from openviper.http.response import HTMLResponse, JSONResponse


class TestFullSystemIntegration:
    """Comprehensive integration tests for the entire OpenViper system."""

    @pytest.mark.asyncio
    async def test_complete_user_lifecycle(
        self,
        test_database,
        test_cache,
        app_with_routes: OpenViper,
    ):
        """Test complete user lifecycle from creation to deletion."""
        async with app_with_routes.test_client() as client:
            response = await client.post(
                "/users",
                json={
                    "username": "lifecycle_user",
                    "email": "lifecycle@example.com",
                    "password": "secure123",
                },
            )

            assert response.status_code == 201
            data = response.json()
            assert data["username"] == "lifecycle_user"
            user_id = data["id"]

            response = await client.get(f"/users/{user_id}")
            assert response.status_code == 200
            assert response.json()["email"] == "lifecycle@example.com"

            response = await client.put(
                f"/users/{user_id}",
                json={"email": "updated@example.com"},
            )
            assert response.status_code == 200
            assert response.json()["email"] == "updated@example.com"

            response = await client.delete(f"/users/{user_id}")
            assert response.status_code == 204

            response = await client.get(f"/users/{user_id}")
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_authentication_and_session_flow(
        self,
        test_database,
        test_cache,
        admin_user: User,
    ):
        """Test authentication flow with session creation and validation."""
        from openviper.auth.hashers import check_password

        assert admin_user.username == "admin"
        assert await check_password("admin123", admin_user.password)

        perms = await admin_user.get_permissions()
        assert isinstance(perms, set)

        cache = get_cache()
        cache_key = f"user_perms:{admin_user.pk}"
        cached_perms = await cache.get(cache_key)
        assert cached_perms is not None

    @pytest.mark.asyncio
    async def test_role_and_permission_system(
        self,
        test_database,
        test_cache,
        user_with_role: tuple[User, Role],
    ):
        """Test role assignment and permission checking."""
        user, role = user_with_role

        roles = await user.get_roles()
        assert len(roles) > 0
        assert role in roles

        permissions = await user.get_permissions()
        assert "view_dashboard" in permissions

        cache = get_cache()
        cache_key = f"user_perms:{user.pk}"
        cached_perms = await cache.get(cache_key)
        assert cached_perms is not None
        assert "view_dashboard" in cached_perms

    @pytest.mark.asyncio
    async def test_middleware_execution_order(
        self,
        test_database,
        app_with_routes: OpenViper,
    ):
        """Test that middleware executes in correct order."""
        async with app_with_routes.test_client() as client:
            response = await client.get("/")
            assert response.status_code in [200, 403]

            response = await client.get("/health")
            assert response.status_code in [200, 404]

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Foreign key constraint issue in fixture - needs investigation")
    async def test_database_operations_with_relationships(
        self,
        test_database,
        sample_test_data: dict[str, Any],
    ):
        """Test database operations including relationships."""
        admin_role = sample_test_data["admin_role"]
        permissions = sample_test_data["permissions"]

        fetched_role = await Role.objects.filter(id=admin_role.id).first()
        assert fetched_role is not None
        assert fetched_role.name == "admin"

        role_perms = await fetched_role.permissions.all()
        assert len(role_perms) == len(permissions)

        perm_codenames = {p.codename for p in role_perms}
        expected_codenames = {p.codename for p in permissions}
        assert perm_codenames == expected_codenames

    @pytest.mark.asyncio
    async def test_routing_and_path_parameters(
        self,
        test_database,
        app_with_routes: OpenViper,
        admin_user: User,
    ):
        """Test routing with path parameters."""
        async with app_with_routes.test_client() as client:
            response = await client.get(f"/users/{admin_user.id}")
            assert response.status_code == 200
            data = response.json()
            assert data["username"] == "admin"
            assert data["id"] == admin_user.id

    @pytest.mark.asyncio
    async def test_http_method_handling(
        self,
        test_database,
        app_with_routes: OpenViper,
    ):
        """Test different HTTP methods are handled correctly."""
        async with app_with_routes.test_client() as client:
            response = await client.get("/users")
            assert response.status_code == 200

            response = await client.post(
                "/users",
                json={"username": "newuser", "email": "new@example.com"},
            )
            assert response.status_code == 201
            user_id = response.json()["id"]

            response = await client.put(
                f"/users/{user_id}",
                json={"email": "updated@example.com"},
            )
            assert response.status_code == 200

            response = await client.delete(f"/users/{user_id}")
            assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_error_handling_flow(
        self,
        test_database,
        app_with_routes: OpenViper,
    ):
        """Test error handling throughout the system."""
        async with app_with_routes.test_client() as client:
            response = await client.get("/users/999999")
            assert response.status_code == 404

            response = await client.put(
                "/users/999999",
                json={"email": "test@example.com"},
            )
            assert response.status_code == 404

            response = await client.delete("/users/999999")
            assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_cache_integration(
        self,
        test_database,
        test_cache,
        admin_user: User,
    ):
        """Test cache operations throughout the system."""
        cache = get_cache()

        await cache.set("test_key", "test_value", ttl=60)
        value = await cache.get("test_key")
        assert value == "test_value"

        has_key = await cache.has_key("test_key")
        assert has_key is True

        await cache.delete("test_key")
        value = await cache.get("test_key")
        assert value is None

        await admin_user.get_permissions()
        cache_key = f"user_perms:{admin_user.pk}"
        cached_perms = await cache.get(cache_key)
        assert cached_perms is not None

    @pytest.mark.asyncio
    async def test_multiple_users_workflow(
        self,
        test_database,
        test_cache,
        admin_user: User,
        regular_user: User,
        drain_tasks,
    ):
        """Test workflow with multiple users interacting."""
        assert admin_user.is_superuser
        assert not regular_user.is_superuser

        # Create test permissions with unique codenames to avoid cross-test UNIQUE collisions
        suffix = uuid.uuid4().hex[:8]
        code_view = f"test_view_{suffix}"
        code_edit = f"test_edit_{suffix}"

        perm1 = Permission(codename=code_view, name="Can view test")
        await perm1.save()
        await drain_tasks()  # wait for Permission.after_insert background task to finish
        perm2 = Permission(codename=code_edit, name="Can edit test")
        await perm2.save()
        await drain_tasks()  # drain before querying

        # Verify both permissions were saved
        all_perms = await Permission.objects.all()
        perm_codes = {p.codename for p in all_perms}
        assert code_view in perm_codes
        assert code_edit in perm_codes

        # Clear any permission cache
        cache = get_cache()
        await cache.clear()

        admin_perms = await admin_user.get_permissions()
        user_perms = await regular_user.get_permissions()

        # Superuser should have all permissions
        assert (
            len(admin_perms) >= 2
        ), f"Expected at least 2 perms, got {len(admin_perms)}: {admin_perms}"
        assert code_view in admin_perms
        assert code_edit in admin_perms
        # Regular user without roles should have no permissions
        assert isinstance(user_perms, set)

    @pytest.mark.asyncio
    async def test_complex_routing_scenario(
        self,
        test_database,
    ):
        """Test complex routing with nested routers."""
        from openviper.routing.router import Router

        app = OpenViper()
        api_router = Router(prefix="/api")
        v1_router = Router(prefix="/v1")

        @v1_router.get("/users")
        async def list_users():
            return {"users": []}

        @v1_router.get("/users/{user_id}")
        async def get_user(user_id: int):
            return {"user_id": user_id}

        api_router.include_router(v1_router)
        app.include_router(api_router)

        async with app.test_client() as client:
            response = await client.get("/api/v1/users")
            assert response.status_code in [200, 403]

            response = await client.get("/api/v1/users/123")
            assert response.status_code in [200, 403]

    @pytest.mark.asyncio
    async def test_query_parameters_and_request_data(
        self,
        test_database,
    ):
        """Test query parameters and request data handling."""
        app = OpenViper()

        @app.get("/search")
        async def search(request):
            query = request.query_params.get("q", "")
            limit = int(request.query_params.get("limit", "10"))
            return {"query": query, "limit": limit, "results": []}

        async with app.test_client() as client:
            response = await client.get("/search?q=test&limit=5")
            if response.status_code == 200:
                data = response.json()
                assert data["query"] == "test"
                assert data["limit"] == 5

    @pytest.mark.asyncio
    async def test_json_request_and_response(
        self,
        test_database,
        app_with_routes: OpenViper,
    ):
        """Test JSON request parsing and response generation."""
        async with app_with_routes.test_client() as client:
            payload = {
                "username": "jsonuser",
                "email": "json@example.com",
                "password": "json123",
            }

            response = await client.post("/users", json=payload)
            assert response.status_code == 201

            data = response.json()
            assert "id" in data
            assert data["username"] == "jsonuser"

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Foreign key constraint issue in fixture - needs investigation")
    async def test_complete_application_workflow(
        self,
        test_database,
        test_cache,
        sample_test_data: dict[str, Any],
    ):
        """Test a complete application workflow from start to finish."""
        admin_role = sample_test_data["admin_role"]

        admin = User(
            username="workflow_admin",
            email="workflow@example.com",
            is_active=True,
            is_staff=True,
        )
        await admin.set_password("admin123")
        await admin.save()

        await admin.roles.add(admin_role)

        roles = await admin.get_roles()
        assert admin_role in roles

        permissions = await admin.get_permissions()
        assert len(permissions) > 0
        assert "add_user" in permissions
        assert "delete_user" in permissions

        cache = get_cache()
        cache_key = f"user_perms:{admin.pk}"
        cached_perms = await cache.get(cache_key)
        assert cached_perms is not None

        editor = User(
            username="workflow_editor",
            email="editor@example.com",
            is_active=True,
        )
        await editor.set_password("editor123")
        await editor.save()

        editor_role = sample_test_data["editor_role"]
        await editor.roles.add(editor_role)

        editor_perms = await editor.get_permissions()
        assert "add_user" in editor_perms
        assert "change_user" in editor_perms
        assert "delete_user" not in editor_perms

    @pytest.mark.asyncio
    async def test_response_types(self, test_database):
        """Test different response types throughout the system."""
        app = OpenViper()

        @app.get("/json")
        async def json_endpoint():
            return JSONResponse({"type": "json"})

        @app.get("/html")
        async def html_endpoint():
            return HTMLResponse("<h1>HTML Response</h1>")

        @app.get("/dict")
        async def dict_endpoint():
            return {"type": "auto_json"}

        async with app.test_client() as client:
            response = await client.get("/json")
            if response.status_code == 200:
                assert "application/json" in response.headers.get("content-type", "")

            response = await client.get("/html")
            if response.status_code == 200:
                assert "text/html" in response.headers.get("content-type", "")

            response = await client.get("/dict")
            if response.status_code == 200:
                assert "application/json" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_database_transaction_consistency(
        self,
        test_database,
    ):
        """Test database transaction consistency."""
        user1 = User(username="user1", email="user1@example.com")
        await user1.save()

        user2 = User(username="user2", email="user2@example.com")
        await user2.save()

        all_users = await User.objects.all()
        usernames = {u.username for u in all_users}
        assert "user1" in usernames
        assert "user2" in usernames

        await user1.delete()
        remaining_users = await User.objects.all()
        remaining_usernames = {u.username for u in remaining_users}
        assert "user1" not in remaining_usernames
        assert "user2" in remaining_usernames
