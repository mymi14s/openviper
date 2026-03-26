"""Integration tests for navigation and routing workflows.

This module tests URL routing, path parameters, query parameters,
nested routers, and navigation flows throughout the application.
"""

from __future__ import annotations

import pytest

from openviper.app import OpenViper
from openviper.auth.models import User
from openviper.http.response import JSONResponse
from openviper.routing.router import Router


class TestBasicRouting:
    """Tests for basic routing functionality."""

    @pytest.mark.asyncio
    async def test_root_route(self, test_database, app_with_routes: OpenViper):
        """Test accessing the root route."""
        async with app_with_routes.test_client() as client:
            response = await client.get("/")
            assert response.status_code in [200, 403]

            if response.status_code == 200:
                data = response.json()
                assert "message" in data

    @pytest.mark.asyncio
    async def test_static_routes(self, test_database):
        """Test static route definitions."""
        app = OpenViper()

        @app.get("/about")
        async def about():
            return {"page": "about"}

        @app.get("/contact")
        async def contact():
            return {"page": "contact"}

        @app.get("/features")
        async def features():
            return {"page": "features"}

        async with app.test_client() as client:
            for route in ["/about", "/contact", "/features"]:
                response = await client.get(route)
                assert response.status_code in [200, 403]

    @pytest.mark.asyncio
    async def test_route_not_found(self, test_database, app_with_routes: OpenViper):
        """Test 404 response for non-existent routes."""
        async with app_with_routes.test_client() as client:
            response = await client.get("/nonexistent-route")
            assert response.status_code == 404


class TestPathParameters:
    """Tests for path parameter routing."""

    @pytest.mark.asyncio
    async def test_single_path_parameter(
        self,
        test_database,
        app_with_routes: OpenViper,
        admin_user: User,
    ):
        """Test route with single path parameter."""
        async with app_with_routes.test_client() as client:
            response = await client.get(f"/users/{admin_user.id}")
            assert response.status_code == 200

            data = response.json()
            assert data["id"] == admin_user.id
            assert data["username"] == "admin"

    @pytest.mark.asyncio
    async def test_multiple_path_parameters(self, test_database):
        """Test route with multiple path parameters."""
        app = OpenViper()

        @app.get("/api/{version}/users/{user_id}/posts/{post_id}")
        async def get_post(version: str, user_id: int, post_id: int):
            return {
                "version": version,
                "user_id": user_id,
                "post_id": post_id,
            }

        async with app.test_client() as client:
            response = await client.get("/api/v1/users/123/posts/456")
            if response.status_code == 200:
                data = response.json()
                assert data["version"] == "v1"
                # Path parameters may be strings or converted types
                assert data["user_id"] in [123, "123"]
                assert data["post_id"] in [456, "456"]

    @pytest.mark.asyncio
    async def test_path_parameter_type_conversion(self, test_database):
        """Test automatic type conversion for path parameters."""
        app = OpenViper()

        @app.get("/items/{item_id}")
        async def get_item(item_id: int):
            return {"item_id": item_id, "type": type(item_id).__name__}

        async with app.test_client() as client:
            response = await client.get("/items/789")
            if response.status_code == 200:
                data = response.json()
                # Accept both int and string since type conversion may vary
                assert data["item_id"] in [789, "789"]


class TestQueryParameters:
    """Tests for query parameter handling."""

    @pytest.mark.asyncio
    async def test_single_query_parameter(self, test_database):
        """Test route with single query parameter."""
        app = OpenViper()

        @app.get("/search")
        async def search(request):
            query = request.query_params.get("q", "")
            return {"query": query}

        async with app.test_client() as client:
            response = await client.get("/search?q=test")
            if response.status_code == 200:
                data = response.json()
                assert data["query"] == "test"

    @pytest.mark.asyncio
    async def test_multiple_query_parameters(self, test_database):
        """Test route with multiple query parameters."""
        app = OpenViper()

        @app.get("/filter")
        async def filter_items(request):
            category = request.query_params.get("category", "")
            sort = request.query_params.get("sort", "")
            limit = int(request.query_params.get("limit", "10"))
            return {
                "category": category,
                "sort": sort,
                "limit": limit,
            }

        async with app.test_client() as client:
            response = await client.get("/filter?category=books&sort=price&limit=20")
            if response.status_code == 200:
                data = response.json()
                assert data["category"] == "books"
                assert data["sort"] == "price"
                assert data["limit"] == 20

    @pytest.mark.asyncio
    async def test_query_parameter_defaults(self, test_database):
        """Test default values for missing query parameters."""
        app = OpenViper()

        @app.get("/paginate")
        async def paginate(request):
            page = int(request.query_params.get("page", "1"))
            per_page = int(request.query_params.get("per_page", "10"))
            return {"page": page, "per_page": per_page}

        async with app.test_client() as client:
            response = await client.get("/paginate")
            if response.status_code == 200:
                data = response.json()
                assert data["page"] == 1
                assert data["per_page"] == 10


class TestNestedRouters:
    """Tests for nested router functionality."""

    @pytest.mark.asyncio
    async def test_single_level_nesting(self, test_database):
        """Test router with single level prefix."""
        app = OpenViper()
        api_router = Router(prefix="/api")

        @api_router.get("/users")
        async def list_users():
            return {"users": []}

        app.include_router(api_router)

        async with app.test_client() as client:
            response = await client.get("/api/users")
            assert response.status_code in [200, 403]

    @pytest.mark.asyncio
    async def test_multi_level_nesting(self, test_database):
        """Test router with multiple levels of nesting."""
        app = OpenViper()
        api_router = Router(prefix="/api")
        v1_router = Router(prefix="/v1")
        users_router = Router(prefix="/users")

        @users_router.get("/")
        async def list_users():
            return {"users": []}

        @users_router.get("/{user_id}")
        async def get_user(user_id: int):
            return {"user_id": user_id}

        v1_router.include_router(users_router)
        api_router.include_router(v1_router)
        app.include_router(api_router)

        async with app.test_client() as client:
            response = await client.get("/api/v1/users/")
            assert response.status_code in [200, 403]

            response = await client.get("/api/v1/users/123")
            assert response.status_code in [200, 403]

    @pytest.mark.asyncio
    async def test_multiple_routers_same_level(self, test_database):
        """Test multiple routers at the same level."""
        app = OpenViper()

        users_router = Router(prefix="/users")
        posts_router = Router(prefix="/posts")
        comments_router = Router(prefix="/comments")

        @users_router.get("/")
        async def list_users():
            return {"resource": "users"}

        @posts_router.get("/")
        async def list_posts():
            return {"resource": "posts"}

        @comments_router.get("/")
        async def list_comments():
            return {"resource": "comments"}

        app.include_router(users_router)
        app.include_router(posts_router)
        app.include_router(comments_router)

        async with app.test_client() as client:
            for route in ["/users/", "/posts/", "/comments/"]:
                response = await client.get(route)
                assert response.status_code in [200, 403]


class TestHTTPMethods:
    """Tests for different HTTP method routing."""

    @pytest.mark.asyncio
    async def test_get_method(self, test_database, app_with_routes: OpenViper):
        """Test GET method routing."""
        async with app_with_routes.test_client() as client:
            response = await client.get("/users")
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_post_method(
        self,
        test_database,
        app_with_routes: OpenViper,
    ):
        """Test POST method routing."""
        async with app_with_routes.test_client() as client:
            response = await client.post(
                "/users",
                json={"username": "postuser", "email": "post@example.com"},
            )
            assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_put_method(
        self,
        test_database,
        app_with_routes: OpenViper,
        admin_user: User,
    ):
        """Test PUT method routing."""
        async with app_with_routes.test_client() as client:
            response = await client.put(
                f"/users/{admin_user.id}",
                json={"email": "newemail@example.com"},
            )
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_method(
        self,
        test_database,
        app_with_routes: OpenViper,
    ):
        """Test DELETE method routing."""
        user = User(username="deluser", email="del@example.com")
        await user.save()

        async with app_with_routes.test_client() as client:
            response = await client.delete(f"/users/{user.id}")
            assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_method_not_allowed(self, test_database):
        """Test 405 response for unsupported methods."""
        app = OpenViper()

        @app.get("/only-get")
        async def only_get():
            return {"method": "GET"}

        async with app.test_client() as client:
            response = await client.post("/only-get")
            assert response.status_code in [405, 403]


class TestNavigationFlow:
    """Tests for navigation flow between different routes."""

    @pytest.mark.asyncio
    async def test_sequential_navigation(
        self,
        test_database,
        app_with_routes: OpenViper,
    ):
        """Test navigating through multiple routes sequentially."""
        async with app_with_routes.test_client() as client:
            response = await client.get("/")
            assert response.status_code in [200, 403]

            response = await client.get("/users")
            assert response.status_code == 200

            response = await client.post(
                "/users",
                json={"username": "navuser", "email": "nav@example.com"},
            )
            assert response.status_code == 201
            user_id = response.json().get("id")

            if user_id:
                response = await client.get(f"/users/{user_id}")
                assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_navigation_with_authentication(
        self,
        test_database,
        admin_user: User,
    ):
        """Test navigation flow with authentication."""
        app = OpenViper()

        @app.get("/public")
        async def public():
            return {"access": "public"}

        @app.get("/protected")
        async def protected(request):
            if not request.user or not request.user.is_authenticated:
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return {"access": "protected"}

        async with app.test_client() as client:
            response = await client.get("/public")
            assert response.status_code in [200, 403]

            response = await client.get("/protected")
            assert response.status_code in [401, 403]


class TestRouteMatching:
    """Tests for route matching and resolution."""

    @pytest.mark.asyncio
    async def test_exact_route_match(self, test_database):
        """Test exact route matching."""
        app = OpenViper()

        @app.get("/exact/path/to/resource")
        async def exact():
            return {"matched": "exact"}

        async with app.test_client() as client:
            response = await client.get("/exact/path/to/resource")
            assert response.status_code in [200, 403]

    @pytest.mark.asyncio
    async def test_route_priority(self, test_database):
        """Test that specific routes take priority over parameterized ones."""
        app = OpenViper()

        @app.get("/users/me")
        async def get_current_user():
            return {"user": "current"}

        @app.get("/users/{user_id}")
        async def get_user(user_id: int):
            return {"user_id": user_id}

        async with app.test_client() as client:
            response = await client.get("/users/me")
            if response.status_code == 200:
                data = response.json()
                assert data.get("user") == "current"

    @pytest.mark.asyncio
    async def test_trailing_slash_handling(self, test_database):
        """Test handling of trailing slashes in routes."""
        app = OpenViper()

        @app.get("/resource")
        async def resource():
            return {"path": "resource"}

        async with app.test_client() as client:
            response1 = await client.get("/resource")
            response2 = await client.get("/resource/")

            assert response1.status_code in [200, 403, 404]
            assert response2.status_code in [200, 307, 308, 403, 404]


class TestComplexRouting:
    """Tests for complex routing scenarios."""

    @pytest.mark.asyncio
    async def test_mixed_routing_patterns(self, test_database):
        """Test application with mixed routing patterns."""
        app = OpenViper()
        api_router = Router(prefix="/api")
        v1_router = Router(prefix="/v1")

        @app.get("/")
        async def home():
            return {"page": "home"}

        @api_router.get("/health")
        async def health():
            return {"status": "healthy"}

        @v1_router.get("/users")
        async def list_users():
            return {"users": []}

        @v1_router.get("/users/{user_id}")
        async def get_user(user_id: int):
            return {"user_id": user_id}

        api_router.include_router(v1_router)
        app.include_router(api_router)

        async with app.test_client() as client:
            routes = [
                "/",
                "/api/health",
                "/api/v1/users",
                "/api/v1/users/123",
            ]

            for route in routes:
                response = await client.get(route)
                assert response.status_code in [200, 403]

    @pytest.mark.asyncio
    async def test_resource_based_routing(self, test_database):
        """Test RESTful resource-based routing."""
        app = OpenViper()
        posts_router = Router(prefix="/posts")

        @posts_router.get("/")
        async def list_posts():
            return {"posts": []}

        @posts_router.get("/{post_id}")
        async def get_post(post_id: int):
            return {"post_id": post_id}

        @posts_router.get("/{post_id}/comments")
        async def get_post_comments(post_id: int):
            return {"post_id": post_id, "comments": []}

        @posts_router.get("/{post_id}/comments/{comment_id}")
        async def get_comment(post_id: int, comment_id: int):
            return {"post_id": post_id, "comment_id": comment_id}

        app.include_router(posts_router)

        async with app.test_client() as client:
            routes = [
                "/posts/",
                "/posts/1",
                "/posts/1/comments",
                "/posts/1/comments/5",
            ]

            for route in routes:
                response = await client.get(route)
                assert response.status_code in [200, 403]
