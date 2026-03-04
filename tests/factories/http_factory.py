from openviper.http.request import Request
from openviper.http.response import JSONResponse, Response


def create_request(
    path: str = "/",
    method: str = "GET",
    headers: list[tuple[bytes, bytes]] | None = None,
    body: bytes = b"",
    **kwargs,
) -> Request:
    """Factory to create a Request object."""
    scope = {
        "type": "http",
        "path": path,
        "method": method,
        "headers": headers or [],
        "query_string": b"",
        **kwargs,
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def create_response(content: str = "Hello", status_code: int = 200, **kwargs) -> Response:
    """Factory to create a Response object."""
    if "media_type" not in kwargs:
        kwargs["media_type"] = "text/plain"
    return Response(content.encode(), status_code=status_code, **kwargs)


def create_json_response(
    data: dict | list | None = None, status_code: int = 200, **kwargs
) -> JSONResponse:
    """Factory to create a JSONResponse object."""
    return JSONResponse(data or {}, status_code=status_code, **kwargs)
