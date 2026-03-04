import pytest

from openviper.routing.router import Router, include
from tests.factories.app_factory import create_application
from tests.utils.test_client import OpenviperTestClient


@pytest.mark.asyncio
async def test_nested_routers_integration():
    app = create_application()

    @app.get("/")
    async def index():
        return "root"

    api_router = Router()
    v1_router = Router()

    @v1_router.get("/users")
    async def list_users():
        return [{"id": 1}]

    api_router.include_router(include(v1_router, prefix="/v1"))
    app.include_router(api_router, prefix="/api")

    async with OpenviperTestClient(app) as client:
        response = await client.get("/api/v1/users")
        assert response.status_code == 200
        assert response.json() == [{"id": 1}]


@pytest.mark.asyncio
async def test_path_params_integration():
    app = create_application()

    @app.get("/")
    async def index():
        return "root"

    @app.get("/items/{item_id}/comments/{comment_id}")
    async def get_comment(item_id: str, comment_id: str):
        return {"item": item_id, "comment": comment_id}

    async with OpenviperTestClient(app) as client:
        response = await client.get("/items/apple/comments/42")
        assert response.status_code == 200
        assert response.json() == {"item": "apple", "comment": "42"}
