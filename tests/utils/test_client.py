from typing import Any

import httpx

from openviper.app import OpenViper


class OpenviperTestClient:
    """A lightweight async test client wrapper around httpx.AsyncClient."""

    def __init__(self, app: OpenViper, base_url: str = "http://testserver"):
        self.app = app
        self.base_url = base_url
        self._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url)

    async def __aenter__(self):
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._client.__aexit__(exc_type, exc_val, exc_tb)

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.get(path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.post(path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.put(path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.patch(path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.delete(path, **kwargs)
