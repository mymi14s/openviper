from typing import Any

from openviper.http.request import Request
from openviper.http.response import HTMLResponse, JSONResponse, Response


def create_request(
    method: str = "GET",
    path: str = "/",
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
    body: bytes = b"",
    path_params: dict[str, Any] | None = None,
    **kwargs,
) -> Request:
    """Create a mock Request object for testing."""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "root_path": "",
        "query_string": query_string,
        "headers": headers or [],
        "path_params": path_params or {},
        **kwargs,
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def create_response(
    content: Any = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    media_type: str | None = None,
) -> Response:
    """Create a Response object for testing."""
    return Response(content, status_code, headers, media_type)


def create_json_response(
    content: Any = None, status_code: int = 200, headers: dict[str, str] | None = None
) -> JSONResponse:
    """Create a JSONResponse object for testing."""
    return JSONResponse(content, status_code, headers)


def create_html_response(
    content: Any = None, status_code: int = 200, headers: dict[str, str] | None = None
) -> HTMLResponse:
    """Create an HTMLResponse object for testing."""
    return HTMLResponse(content, status_code, headers)
