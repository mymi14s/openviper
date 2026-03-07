import builtins
import datetime
import importlib
import json
import os
import sys
import tempfile
import types
import uuid
from unittest.mock import MagicMock, patch

import pytest

import openviper.http.response as resp_mod
from openviper.http.response import (
    FileResponse,
    GZipResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
    _get_jinja2_env,
    _json_encode,
)


@pytest.mark.asyncio
async def test_response_base():
    r = Response("content", status_code=201, headers={"X-Custom": "val"})
    assert r.status_code == 201
    assert r.body == b"content"
    assert r.headers["x-custom"] == "val"

    # Cookie tests
    r.set_cookie("session", "123", max_age=3600, secure=True, httponly=True)
    cookies = r.headers.getlist("set-cookie")
    assert any("session=123" in c and "Max-Age=3600" in c and "Secure" in c for c in cookies)

    r.delete_cookie("session")
    cookies2 = r.headers.getlist("set-cookie")
    assert any("Max-Age=0" in c for c in cookies2)

    # Encoding error
    with pytest.raises(TypeError):
        Response({"obj": 1})  # Response expects str, bytes or None

    # None body
    r2 = Response(None)
    assert r2.body == b""


@pytest.mark.asyncio
async def test_response_asgi_call():
    r = Response(b"data", status_code=200)

    sends = []

    async def fake_send(msg):
        sends.append(msg)

    await r({}, None, fake_send)
    assert len(sends) == 2
    assert sends[0]["type"] == "http.response.start"
    assert sends[0]["status"] == 200
    assert sends[1]["type"] == "http.response.body"
    assert sends[1]["body"] == b"data"
    assert sends[1]["more_body"] is False


@pytest.mark.asyncio
async def test_json_response():
    data = {
        "str": "1",
        "dt": datetime.datetime(2023, 1, 1, 12, 0),
        "d": datetime.date(2023, 1, 1),
        "id": uuid.UUID("12345678123456781234567812345678"),
    }
    r = JSONResponse(data)
    assert r.media_type == "application/json"

    parsed = json.loads(r.body.decode("utf-8"))
    assert parsed["dt"] == "2023-01-01T12:00:00"
    assert parsed["d"] == "2023-01-01"
    assert parsed["id"] == "12345678-1234-5678-1234-567812345678"

    with pytest.raises(TypeError):
        JSONResponse({"fn": lambda x: x})


@pytest.mark.asyncio
async def test_html_response():
    r = HTMLResponse("<h1>Hi</h1>")
    assert r.media_type == "text/html"
    assert r.body == b"<h1>Hi</h1>"

    # Template rendering tests require jinja2
    with pytest.raises(ValueError, match="Cannot specify both 'content' and 'template'"):
        HTMLResponse("foo", template="bar.html")

    # Mock _get_jinja2_env to test template branch (cached env factory)
    mock_env = MagicMock()
    mock_template = MagicMock()
    mock_template.render.return_value = "rendered html"
    mock_env.get_template.return_value = mock_template

    with patch("openviper.http.response._get_jinja2_env", return_value=mock_env):
        r2 = HTMLResponse(template="index.html", context={"foo": "bar"})
        assert r2.body == b"rendered html"
        mock_template.render.assert_called_once_with(foo="bar")


@pytest.mark.asyncio
async def test_html_response_no_jinja2():
    with (
        patch("openviper.http.response.Environment", None),
        pytest.raises(ImportError, match="jinja2 is required"),
    ):
        HTMLResponse(template="index.html")


def test_plain_text_response():
    r = PlainTextResponse("text")
    assert r.media_type == "text/plain"


def test_redirect_response():
    r = RedirectResponse("/login")
    assert r.status_code == 307
    assert r.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_streaming_response():
    async def async_gen():
        yield b"chunk1"
        yield b"chunk2"

    sends = []

    async def fake_send(msg):
        sends.append(msg)

    r = StreamingResponse(async_gen())
    await r({}, None, fake_send)

    # Start, chunk1, chunk2, empty end
    assert len(sends) == 4
    assert sends[1]["body"] == b"chunk1"
    assert sends[2]["body"] == b"chunk2"
    assert sends[3]["body"] == b""
    assert sends[3]["more_body"] is False

    # Sync iterators
    def sync_gen():
        yield b"s1"
        yield b"s2"

    sends.clear()
    r2 = StreamingResponse(sync_gen)  # Callable
    await r2({}, None, fake_send)
    assert len(sends) == 4
    assert sends[1]["body"] == b"s1"


@pytest.mark.asyncio
async def test_file_response():
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(b"file data")
        tf.flush()

        try:
            r = FileResponse(tf.name, filename="download.txt")
            assert "content-length" in r.headers
            assert r.headers["content-disposition"] == 'attachment; filename="download.txt"'

            sends = []

            async def fake_send(msg):
                sends.append(msg)

            await r({}, None, fake_send)
            assert len(sends) == 3
            assert sends[1]["body"] == b"file data"
            assert sends[2]["body"] == b""
            assert sends[2]["more_body"] is False

        finally:
            os.remove(tf.name)


@pytest.mark.asyncio
async def test_gzip_response():
    # Long enough to bypass min block
    data = b"a" * 1000
    inner = Response(data)

    r = GZipResponse(inner, minimum_size=500)

    sends = []

    async def fake_send(msg):
        sends.append(msg)

    await r({}, None, fake_send)
    assert len(sends) == 2
    assert sends[0]["headers"]  # has gzip

    # Below min threshold
    data2 = b"a" * 100
    inner2 = Response(data2)
    r2 = GZipResponse(inner2, minimum_size=500)

    sends.clear()
    await r2({}, None, fake_send)
    assert sends[1]["body"] == b"a" * 100  # unchanged


def test_response_module_no_jinja2():

    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "jinja2":
            raise ImportError("Simulated missing jinja2")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        importlib.reload(resp_mod)
    try:
        assert resp_mod.Environment is None
        assert resp_mod.FileSystemLoader is None
    finally:
        importlib.reload(resp_mod)  # restore with real jinja2


def test_json_encode_non_2_indent():

    encoded = _json_encode({"key": "value"}, default=None, indent=4)
    parsed = json.loads(encoded)
    assert parsed == {"key": "value"}
    assert b"\n" in encoded  # json.dumps with indent produces newlines


def test_get_jinja2_env_no_jinja2():
    from openviper.http.response import _get_jinja2_env

    _get_jinja2_env.cache_clear()
    with patch("openviper.http.response.Environment", None):
        with pytest.raises(ImportError, match="jinja2 is required"):
            _get_jinja2_env(("unique_test_path_no_jinja2_abc",))
    _get_jinja2_env.cache_clear()


def test_response_cookie_expires():
    r = Response("body")
    r.set_cookie("sid", "abc", expires=1735689600)
    cookies = r.headers.getlist("set-cookie")
    assert any("Expires=1735689600" in c for c in cookies)


def test_json_response_default_encoder_directly():
    encoder = JSONResponse._default_encoder

    dt = datetime.datetime(2024, 3, 7, 12, 0, 0)
    assert encoder(dt) == "2024-03-07T12:00:00"

    d = datetime.date(2024, 3, 7)
    assert encoder(d) == "2024-03-07"

    uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert encoder(uid) == "12345678-1234-5678-1234-567812345678"


def test_html_response_template_installed_app_import_error():

    _get_jinja2_env.cache_clear()

    _orig_import = importlib.import_module  # save real function before patching

    mock_env = MagicMock()
    mock_template = MagicMock()
    mock_template.render.return_value = "rendered"
    mock_env.get_template.return_value = mock_template

    def _import_error_for_bad_app(name, *args, **kwargs):
        if name == "invalid_app_xyz":
            raise ImportError("no such app")
        return _orig_import(name, *args, **kwargs)

    with (
        patch("openviper.http.response.settings") as mock_settings,
        patch(
            "openviper.http.response.importlib.import_module",
            side_effect=_import_error_for_bad_app,
        ),
        patch("openviper.http.response._get_jinja2_env", return_value=mock_env),
    ):
        mock_settings.INSTALLED_APPS = ("invalid_app_xyz",)
        r = HTMLResponse(template="test.html", context={})

    assert r.body == b"rendered"
    _get_jinja2_env.cache_clear()


def test_html_response_template_installed_app_templates_found(tmp_path):

    _get_jinja2_env.cache_clear()

    fake_mod_name = "fake_app_with_templates_openviper_test"
    fake_mod = types.ModuleType(fake_mod_name)
    app_dir = tmp_path / fake_mod_name
    app_dir.mkdir()
    (app_dir / "templates").mkdir()
    fake_mod.__file__ = str(app_dir / "__init__.py")
    sys.modules[fake_mod_name] = fake_mod

    captured_paths: list[str] = []

    def fake_jinja2_env(paths: tuple) -> MagicMock:
        captured_paths.extend(paths)
        env = MagicMock()
        tmpl = MagicMock()
        tmpl.render.return_value = "ok"
        env.get_template.return_value = tmpl
        return env

    try:
        with (
            patch("openviper.http.response.settings") as mock_settings,
            patch("openviper.http.response._get_jinja2_env", side_effect=fake_jinja2_env),
        ):
            mock_settings.INSTALLED_APPS = (fake_mod_name,)
            r = HTMLResponse(template="hello.html", context={})

        assert r.body == b"ok"
        assert str(app_dir / "templates") in captured_paths
    finally:
        sys.modules.pop(fake_mod_name, None)
        _get_jinja2_env.cache_clear()
