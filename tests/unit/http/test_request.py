import pytest

from openviper.http.request import URL, Request, UploadFile
from openviper.utils.datastructures import ImmutableMultiDict


@pytest.mark.asyncio
async def test_upload_file():
    class FakeFile:
        def read(self, s):
            return b"data"

        def seek(self, o):
            self.offset = o

        def close(self):
            self.closed = True

    ff = FakeFile()
    uf = UploadFile("test.txt", "text/plain", ff)

    assert await uf.read() == b"data"
    await uf.seek(0)
    assert ff.offset == 0
    await uf.close()
    assert ff.closed is True
    assert repr(uf) == "UploadFile(filename='test.txt', content_type='text/plain')"


def test_url_parsing():
    scope = {
        "scheme": "http",
        "server": ("127.0.0.1", 80),
        "path": "/test",
        "query_string": b"a=1",
    }
    url = URL(scope)
    assert url.scheme == "http"
    assert url.host == "127.0.0.1"
    assert url.path == "/test"
    assert url.query_string == "a=1"
    assert str(url) == "http://127.0.0.1/test?a=1"
    assert repr(url) == "URL('http://127.0.0.1/test?a=1')"

    # Custom port
    scope["server"] = ("127.0.0.1", 8080)
    url2 = URL(scope)
    assert url2.host == "127.0.0.1:8080"

    # Fallback to header
    scope.pop("server")
    scope["headers"] = [(b"host", b"example.org")]
    url3 = URL(scope)
    assert url3.host == "example.org"


def test_request_properties():
    scope = {
        "type": "http",
        "method": "post",
        "scheme": "https",
        "server": ("localhost", 443),
        "path": "/api",
        "root_path": "/root",
        "headers": [
            (b"cookie", b"session=123; theme=dark"),
            (b"content-type", b"application/json"),
        ],
        "query_string": b"q=search",
        "client": ("1.2.3.4", 5555),
    }
    req = Request(scope)

    assert req.method == "POST"
    assert str(req.url) == "https://localhost/api?q=search"
    assert req.path == "/api"
    assert req.root_path == "/root"
    assert req.headers["content-type"] == "application/json"
    assert req.query_params["q"] == "search"
    assert req.cookies == {"session": "123", "theme": "dark"}
    assert req.client == ("1.2.3.4", 5555)
    assert req.is_secure() is True
    assert "<Request [POST]" in repr(req)


@pytest.mark.asyncio
async def test_request_body_reading():
    scope = {"type": "http", "method": "post", "headers": [(b"content-type", b"application/json")]}

    messages = [{"body": b'{"a"', "more_body": True}, {"body": b": 1}", "more_body": False}]
    idx = 0

    async def fake_receive():
        nonlocal idx
        msg = messages[idx]
        idx += 1
        return msg

    req = Request(scope, fake_receive)

    body = await req.body()
    assert body == b'{"a": 1}'

    # Subsequent calls should return cached body
    assert await req.body() == b'{"a": 1}'

    # test JSON
    assert await req.json() == {"a": 1}


@pytest.mark.asyncio
async def test_request_form_parsing():
    scope = {
        "type": "http",
        "method": "post",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
    }

    async def fake_receive():
        return {"body": b"field1=val1&field2=val2", "more_body": False}

    req = Request(scope, fake_receive)
    form = await req.form()
    assert isinstance(form, ImmutableMultiDict)
    assert form["field1"] == "val1"


@pytest.mark.asyncio
async def test_request_multipart_fallback():
    scope = {
        "type": "http",
        "method": "post",
        "headers": [(b"content-type", b"multipart/form-data")],
    }

    async def fake_receive():
        return {"body": b"binary data", "more_body": False}

    req = Request(scope, fake_receive)
    form = await req.form()
    # Multipart parsing is currently a fallback empty dict in code
    assert len(form) == 0


@pytest.mark.asyncio
async def test_request_stream():
    scope = {"type": "http", "method": "post"}
    messages = [{"body": b"chunk1", "more_body": True}, {"body": b"chunk2", "more_body": False}]
    idx = 0

    async def fake_receive():
        nonlocal idx
        if idx >= len(messages):
            return {"body": b"", "more_body": False}
        msg = messages[idx]
        idx += 1
        return msg

    req = Request(scope, fake_receive)

    chunks = []
    async for chunk in req.stream():
        chunks.append(chunk)

    assert chunks == [b"chunk1", b"chunk2"]

    # Test cached body branch
    req2 = Request(scope, fake_receive)
    req2._body = b"chunk1chunk2"
    chunks2 = []
    async for chunk in req2.stream():
        chunks2.append(chunk)

    assert chunks2 == [b"chunk1chunk2"]
