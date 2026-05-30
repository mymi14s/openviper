import pytest

from openviper.http.request import Request, UploadFile


@pytest.mark.asyncio
async def test_request_multipart_parsing():
    """Test that Request.form() correctly parses multipart data."""
    boundary = "vipersboundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="title"\r\n\r\n'
        "Viper Post\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "Viper content\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", f"multipart/form-data; boundary={boundary}".encode())],
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(scope, receive)
    form = await request.form()

    assert form["title"] == "Viper Post"
    assert isinstance(form["file"], UploadFile)
    assert form["file"].filename == "test.txt"
    assert await form["file"].read() == b"Viper content"


@pytest.mark.asyncio
async def test_request_multipart_empty_file():
    """Test that Request.form() handles empty files correctly."""
    boundary = "emptyboundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="empty"; filename="empty.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        f"\r\n--{boundary}--\r\n"
    ).encode()

    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", f"multipart/form-data; boundary={boundary}".encode())],
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(scope, receive)
    form = await request.form()

    assert "empty" in form
    assert await form["empty"].read() == b""


@pytest.mark.asyncio
async def test_body_available_after_form_parsing():
    """stream() must cache consumed bytes so body() still works after form()."""
    boundary = "cacheboundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="field"\r\n\r\n'
        "value\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", f"multipart/form-data; boundary={boundary}".encode())],
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(scope, receive)
    form = await request.form()
    assert form["field"] == "value"

    # After form() consumed the stream, body() must return the cached bytes.
    raw = await request.body()
    assert raw == body
