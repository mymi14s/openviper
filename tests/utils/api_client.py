from typing import Any

from .test_client import OpenviperTestClient


class APIClient(OpenviperTestClient):
    """An API-specific test client with helper methods for JSON requests."""

    async def json_post(self, path: str, data: Any, **kwargs: Any):
        return await self.post(path, json=data, **kwargs)

    async def json_put(self, path: str, data: Any, **kwargs: Any):
        return await self.put(path, json=data, **kwargs)

    async def json_patch(self, path: str, data: Any, **kwargs: Any):
        return await self.patch(path, json=data, **kwargs)
