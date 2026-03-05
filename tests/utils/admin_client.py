from __future__ import annotations

import json
from typing import Any

from openviper.auth.jwt import create_access_token


class AdminClient:
    """Specialized client for testing the admin API."""

    def __init__(self, app: Any):
        self.app = app
        self.access_token = None

    def login(self, user: Any):
        """Pre-authenticate the client with a user's token."""
        self.access_token = create_access_token(user.id, {"username": user.username})

    def _get_headers(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        h = headers.copy() if headers else {}
        if self.access_token:
            h["Authorization"] = f"Bearer {self.access_token}"
        return h

    async def _request(
        self,
        method: str,
        path: str,
        data: dict | None = None,
        params: dict | None = None,
        headers: dict | None = None,
        cookies: dict | None = None,
    ) -> Any:
        # Construct path with params
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            path = f"{path}?{query}"

        {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [
                (k.lower().encode(), v.encode()) for k, v in self._get_headers(headers).items()
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 80),
            "scheme": "http",
            "http_version": "1.1",
        }

        json.dumps(data).encode() if data else b""

        # This is a bit simplified, but enough for our integration tests
        # The real app uses ASGI, so we'd normally use httpx.AsyncClient(app=app)
        # But for absolute lifecycle control without external libs in this specific way:
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test"
        ) as client:
            resp = await client.request(
                method=method,
                url=path,
                json=data,
                params=params,
                headers=self._get_headers(headers),
                cookies=cookies,
            )
            return resp

    async def get(self, path: str, **kwargs):
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs):
        return await self._request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs):
        return await self._request("PUT", path, **kwargs)

    async def patch(self, path: str, **kwargs):
        return await self._request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs):
        return await self._request("DELETE", path, **kwargs)
