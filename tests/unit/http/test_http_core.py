import json

import pytest

from openviper.http.request import Request
from openviper.http.response import JSONResponse, Response


@pytest.mark.asyncio
async def test_request_properties():
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/test",
        "headers": [(b"content-type", b"application/json"), (b"x-test", b"value")],
        "query_string": b"a=1&b=2",
    }

    async def receive():
        return {"type": "http.request", "body": b'{"foo": "bar"}'}

    request = Request(scope, receive)
    assert request.method == "POST"
    assert request.path == "/test"
    assert request.headers["x-test"] == "value"
    assert request.query_params["a"] == "1"

    body = await request.body()
    assert body == b'{"foo": "bar"}'

    json_data = await request.json()
    assert json_data == {"foo": "bar"}


def test_response_basics():
    response = Response(b"hello", status_code=201, headers={"X-Custom": "val"})
    assert response.status_code == 201
    assert response.body == b"hello"
    assert response.headers["X-Custom"] == "val"
    assert response.media_type is None


def test_json_response():
    response = JSONResponse({"a": 1})
    assert response.media_type == "application/json"
    assert json.loads(response.body) == {"a": 1}


@pytest.mark.asyncio
async def test_request_form_data():
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
    }

    async def receive():
        return {"type": "http.request", "body": b"field1=value1&field2=value2"}

    request = Request(scope, receive)
    form = await request.form()
    assert form["field1"] == "value1"
    assert form["field2"] == "value2"
