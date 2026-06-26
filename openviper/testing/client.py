"""Async HTTP client helpers for OpenViper tests."""

import typing as t

if t.TYPE_CHECKING:
    import httpx

    from openviper.app import OpenViper


class OpenViperTestClient:
    """Context-managed async client bound to an OpenViper ASGI app."""

    def __init__(self, app: OpenViper, base_url: str = "http://testserver") -> None:
        self.app = app
        self.base_url = base_url
        self.client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> httpx.AsyncClient:
        self.client = self.app.test_client(base_url=self.base_url, follow_redirects=True)
        return self.client

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None
