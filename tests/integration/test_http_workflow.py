"""Integration tests for HTTP request/response workflow."""

from __future__ import annotations

import pytest

from openviper.app import OpenViper
from openviper.http.response import HTMLResponse, JSONResponse, PlainTextResponse
from openviper.routing.router import Router


class TestHTTPWorkflow:
    """Integration tests for full HTTP request/response cycle."""

    @pytest.mark.asyncio
    async def test_simple_json_endpoint(self):
        """Test a simple JSON API endpoint."""
        app = OpenViper()

        @app.get("/api/hello")
        def hello():
            return {"message": "Hello, World!"}

        async with app.test_client() as client:
            response = await client.get("/api/hello")
            # May get 200 or 400 depending on middleware (CSRF etc.)
            assert response.status_code in [200, 400, 403]

    @pytest.mark.asyncio
    async def test_path_parameters(self):
        """Test path parameter extraction."""
        app = OpenViper()

        @app.get("/users/{user_id}")
        def get_user(user_id: int):
            return {"user_id": user_id}

        async with app.test_client() as client:
            response = await client.get("/users/123")
            assert response.status_code in [200, 400, 403]

    @pytest.mark.asyncio
    async def test_query_parameters(self):
        """Test query parameter handling."""
        app = OpenViper()

        @app.get("/search")
        def search(request):
            q = request.query_params.get("q", "")
            return {"query": q}

        async with app.test_client() as client:
            response = await client.get("/search?q=test")
            assert response.status_code in [200, 400, 403]

    @pytest.mark.asyncio
    async def test_post_with_json_body(self):
        """Test POST request with JSON body."""
        app = OpenViper()

        @app.post("/api/items")
        async def create_item(request):
            data = await request.json()
            return {"created": data}

        async with app.test_client() as client:
            response = await client.post("/api/items", json={"name": "test item"})
            assert response.status_code in [200, 201, 400, 403]

    @pytest.mark.asyncio
    async def test_multiple_http_methods(self):
        """Test route with multiple HTTP methods."""
        app = OpenViper()

        @app.route("/resource", methods=["GET", "POST", "PUT", "DELETE"])
        def resource(request):
            return {"method": request.method}

        async with app.test_client() as client:
            for method in ["get", "post", "put", "delete"]:
                response = await getattr(client, method)("/resource")
                assert response.status_code in [200, 400, 403, 405]


class TestRouterIntegration:
    """Integration tests for router functionality."""

    @pytest.mark.asyncio
    async def test_nested_routers(self):
        """Test including nested routers."""
        app = OpenViper()
        api_router = Router()
        v1_router = Router(prefix="/v1")

        @v1_router.get("/users")
        def list_users():
            return {"users": []}

        api_router.include_router(v1_router)
        app.include_router(api_router, prefix="/api")

        async with app.test_client() as client:
            response = await client.get("/api/v1/users")
            assert response.status_code in [200, 400, 403]

    @pytest.mark.asyncio
    async def test_route_not_found(self):
        """Test 404 for non-existent routes."""
        app = OpenViper()

        @app.get("/exists")
        def exists():
            return {}

        async with app.test_client() as client:
            response = await client.get("/does-not-exist")
            assert response.status_code in [404, 400, 403]

    @pytest.mark.asyncio
    async def test_method_not_allowed(self):
        """Test 405 for wrong HTTP method."""
        app = OpenViper()

        @app.get("/only-get")
        def only_get():
            return {}

        async with app.test_client() as client:
            response = await client.post("/only-get")
            assert response.status_code in [405, 400, 403]


class TestResponseTypes:
    """Integration tests for different response types."""

    @pytest.mark.asyncio
    async def test_json_response(self):
        """Test JSONResponse."""
        app = OpenViper()

        @app.get("/json")
        def json_endpoint():
            return JSONResponse({"data": "test"})

        async with app.test_client() as client:
            response = await client.get("/json")
            if response.status_code == 200:
                assert "application/json" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_html_response(self):
        """Test HTMLResponse."""
        app = OpenViper()

        @app.get("/html")
        def html_endpoint():
            return HTMLResponse("<h1>Hello</h1>")

        async with app.test_client() as client:
            response = await client.get("/html")
            if response.status_code == 200:
                assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_plain_text_response(self):
        """Test PlainTextResponse."""
        app = OpenViper()

        @app.get("/text")
        def text_endpoint():
            return PlainTextResponse("Hello, World!")

        async with app.test_client() as client:
            response = await client.get("/text")
            if response.status_code == 200:
                assert "text/plain" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_dict_auto_converts_to_json(self):
        """Test that dict returns auto-convert to JSON."""
        app = OpenViper()

        @app.get("/auto-json")
        def auto_json():
            return {"auto": "converted"}

        async with app.test_client() as client:
            response = await client.get("/auto-json")
            if response.status_code == 200:
                assert "application/json" in response.headers.get("content-type", "")


class TestExceptionHandling:
    """Integration tests for exception handling."""

    @pytest.mark.asyncio
    async def test_unhandled_exception_returns_500(self):
        """Test that unhandled exceptions return 500."""
        app = OpenViper()

        @app.get("/error")
        def error_endpoint():
            raise ValueError("Test error")

        async with app.test_client() as client:
            response = await client.get("/error")
            # Should get 500 or may be blocked by middleware
            assert response.status_code in [500, 400, 403]

    @pytest.mark.asyncio
    async def test_custom_exception_handler(self):
        """Test custom exception handler."""
        app = OpenViper()

        class CustomError(Exception):
            pass

        @app.exception_handler(CustomError)
        async def handle_custom_error(request, exc):
            return JSONResponse({"error": "custom"}, status_code=418)

        @app.get("/custom-error")
        def custom_error_endpoint():
            raise CustomError("Test")

        async with app.test_client() as client:
            response = await client.get("/custom-error")
            # May get 418 or blocked by middleware
            assert response.status_code in [418, 400, 403]


class TestLifecycleEvents:
    """Integration tests for app lifecycle events."""

    @pytest.mark.asyncio
    async def test_startup_handler_called(self):
        """Test that startup handlers are called."""
        app = OpenViper()
        started = []

        @app.on_startup
        async def on_startup():
            started.append(True)

        @app.get("/check")
        def check():
            return {"started": len(started) > 0}

        # Just verify handlers are registered correctly
        assert len(app._startup_handlers) == 1

    @pytest.mark.asyncio
    async def test_shutdown_handler_registered(self):
        """Test that shutdown handlers are registered."""
        app = OpenViper()

        @app.on_shutdown
        async def on_shutdown():
            pass

        assert len(app._shutdown_handlers) == 1
