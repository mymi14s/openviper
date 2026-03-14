import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.admin.api import views
from openviper.db.fields import CharField, FileField
from openviper.db.models import Model
from openviper.http.request import Request


class FileModel(Model):
    title = CharField(max_length=100)
    image = FileField(upload_to="test_uploads")


@pytest.fixture
def media_setup():
    test_media = Path("./test_media_api").absolute()
    test_media.mkdir(exist_ok=True)
    with patch("openviper.db.fields.settings") as mock_settings:
        mock_settings.MEDIA_DIR = str(test_media)
        yield test_media
    if test_media.exists():
        shutil.rmtree(test_media)


def get_handler(path, method):
    router = views.get_admin_router()
    for route in router.routes:
        if route.path == path and method in route.methods:
            return route.handler
    raise Exception(f"Handler for {method} {path} not found")


def make_multipart_request(boundary, body, user=None):
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", f"multipart/form-data; boundary={boundary}".encode())],
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    req = Request(scope, receive)
    if user:
        req.user = user
    return req


@pytest.mark.asyncio
async def test_create_instance_multipart(media_setup):
    """Test creating an instance via Admin API with multipart data."""
    boundary = "apiboundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="title"\r\n\r\n'
        "API Test\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="image"; filename="api.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
        "png-data\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    request = make_multipart_request(boundary, body)

    mock_admin_obj = MagicMock()
    mock_admin_obj.model = FileModel
    mock_admin_obj.has_add_permission.return_value = True

    with (
        patch(
            "openviper.admin.registry.AdminRegistry.get_model_admin_by_app_and_name",
            return_value=mock_admin_obj,
        ),
        patch(
            "openviper.admin.registry.AdminRegistry.get_model_by_app_and_name",
            return_value=FileModel,
        ),
        patch("openviper.admin.api.views.check_admin_access", return_value=True),
        patch("openviper.admin.api.views.log_change", AsyncMock()),
        patch(
            "openviper.admin.api.views._serialize_instance_with_children",
            AsyncMock(return_value={"id": 1}),
        ),
        patch.object(FileModel, "save", AsyncMock()),
    ):

        handler = get_handler("/models/{app_label}/{model_name}/", "POST")
        response = await handler(request, "app", "filemodel")

        assert response.status_code == 201


@pytest.mark.asyncio
async def test_multipart_json_parsing():
    """Test that nested JSON strings in multipart are correctly parsed."""
    boundary = "jsonboundary"
    child_data = [{"name": "Child 1"}, {"name": "Child 2"}]
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="title"\r\n\r\n'
        "Parent\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="children"\r\n\r\n'
        f"{json.dumps(child_data)}\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    request = make_multipart_request(boundary, body)

    mock_admin_obj = MagicMock()
    mock_admin_obj.model = FileModel
    mock_admin_obj.has_add_permission.return_value = True

    mock_model_cls = MagicMock(spec=FileModel)
    mock_model_cls._fields = {}
    mock_model_cls.return_value = MagicMock(spec=FileModel)

    with (
        patch(
            "openviper.admin.registry.AdminRegistry.get_model_admin_by_app_and_name",
            return_value=mock_admin_obj,
        ),
        patch(
            "openviper.admin.registry.AdminRegistry.get_model_by_app_and_name",
            return_value=mock_model_cls,
        ),
        patch("openviper.admin.api.views.check_admin_access", return_value=True),
        patch("openviper.admin.api.views.log_change", AsyncMock()),
        patch(
            "openviper.admin.api.views._serialize_instance_with_children",
            AsyncMock(return_value={"id": 1}),
        ),
    ):

        handler = get_handler("/models/{app_label}/{model_name}/", "POST")
        await handler(request, "app", "filemodel")

        # Check what was passed to mock_model_cls constructor
        constructor_args = mock_model_cls.call_args[1]
        assert constructor_args["title"] == "Parent"
        assert constructor_args["children"] == child_data
        assert isinstance(constructor_args["children"], list)
