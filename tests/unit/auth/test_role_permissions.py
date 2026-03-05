from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.models import ContentType, User
from openviper.auth.permissions import (
    _CT_PERMISSION_CACHE,
    PermissionError,  # noqa: A004
    check_permission_for_model,
)
from openviper.core.context import current_user as context_current_user
from openviper.core.context import set_current_user
from openviper.db.models import Model


class DummyAppModel(Model):
    class Meta:
        table_name = "testapp_dummyappmodel"


class AuthAppModel(Model):
    class Meta:
        table_name = "auth_authappmodel"


# The ModelMeta metaclass computes _app_name from __module__, overriding any
# class-body assignment.  Set the intended values after class creation.
DummyAppModel._app_name = "testapp"
DummyAppModel._model_name = "DummyAppModel"
AuthAppModel._app_name = "auth"


@pytest.fixture(autouse=True)
def clear_context():
    _CT_PERMISSION_CACHE.clear()
    token = set_current_user(None)
    yield
    context_current_user.reset(token)


# ── helpers ───────────────────────────────────────────────────────────────────


def _mock_ct_objects(ct_or_none):
    """Patch ContentType.objects so filter().first() returns ct_or_none."""
    qs = MagicMock()
    qs.first = AsyncMock(return_value=ct_or_none)
    objs = MagicMock()
    objs.filter.return_value = qs
    return objs


def _mock_ctp_objects(count):
    """Patch ContentTypePermission.objects so filter().count() returns count."""
    qs = MagicMock()
    qs.count = AsyncMock(return_value=count)
    objs = MagicMock()
    objs.filter.return_value = qs
    return objs


# ── bypass cases ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bypass_for_auth_app():
    """Auth app models are always accessible."""
    await check_permission_for_model(AuthAppModel, "read")


@pytest.mark.asyncio
async def test_bypass_ignore_permissions_flag():
    """ignore_permissions=True skips all checks."""
    await check_permission_for_model(DummyAppModel, "delete", ignore_permissions=True)


@pytest.mark.asyncio
async def test_bypass_ignore_permissions_context():
    """ignore_permissions_ctx skips all checks."""
    from openviper.core.context import ignore_permissions_ctx

    token = ignore_permissions_ctx.set(True)
    try:
        await check_permission_for_model(DummyAppModel, "delete")
    finally:
        ignore_permissions_ctx.reset(token)


# ── public model cases ────────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("openviper.auth.models.ContentType.objects")
async def test_public_model_no_content_type(mock_ct_objs):
    """No ContentType registered → model is public."""
    user = User(is_superuser=False)
    user.id = 1
    set_current_user(user)

    mock_ct_objs.filter.return_value = MagicMock(first=AsyncMock(return_value=None))

    await check_permission_for_model(DummyAppModel, "create")
    mock_ct_objs.filter.assert_called_once_with(app_label="testapp", model="DummyAppModel")


@pytest.mark.asyncio
@patch("openviper.auth.models.ContentType.objects")
@patch("openviper.auth.models.ContentTypePermission.objects")
async def test_public_model_no_permissions_configured(mock_ctp_objs, mock_ct_objs):
    """ContentType exists but 0 permissions configured → model is public."""
    user = User(is_superuser=False)
    user.id = 1
    set_current_user(user)

    ct = ContentType(id=1, app_label="testapp", model="DummyAppModel")
    mock_ct_objs.filter.return_value = MagicMock(first=AsyncMock(return_value=ct))
    mock_ctp_objs.filter.return_value = MagicMock(count=AsyncMock(return_value=0))

    await check_permission_for_model(DummyAppModel, "read")


# ── user-context bypass ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("openviper.auth.models.ContentType.objects")
@patch("openviper.auth.models.ContentTypePermission.objects")
async def test_bypass_for_no_user_context(mock_ctp_objs, mock_ct_objs):
    """No user in context → bypass even when permissions are configured."""
    ct = ContentType(id=1, app_label="testapp", model="DummyAppModel")
    mock_ct_objs.filter.return_value = MagicMock(first=AsyncMock(return_value=ct))
    mock_ctp_objs.filter.return_value = MagicMock(count=AsyncMock(return_value=2))

    # No user set (clear_context fixture ensures this)
    await check_permission_for_model(DummyAppModel, "update")


@pytest.mark.asyncio
@patch("openviper.auth.models.ContentType.objects")
@patch("openviper.auth.models.ContentTypePermission.objects")
async def test_bypass_for_superuser(mock_ctp_objs, mock_ct_objs):
    """Superuser bypasses permission check."""
    user = User(is_superuser=True)
    user.id = 1
    set_current_user(user)

    ct = ContentType(id=1, app_label="testapp", model="DummyAppModel")
    mock_ct_objs.filter.return_value = MagicMock(first=AsyncMock(return_value=ct))
    mock_ctp_objs.filter.return_value = MagicMock(count=AsyncMock(return_value=2))

    await check_permission_for_model(DummyAppModel, "delete")


# ── enforcement ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("openviper.auth.models.ContentType.objects")
@patch("openviper.auth.models.ContentTypePermission.objects")
async def test_deny_insufficient_permissions(mock_ctp_objs, mock_ct_objs):
    """has_model_perm returns False → PermissionError raised."""
    user = User(is_superuser=False)
    user.id = 1
    set_current_user(user)

    ct = ContentType(id=1, app_label="testapp", model="DummyAppModel")
    mock_ct_objs.filter.return_value = MagicMock(first=AsyncMock(return_value=ct))
    mock_ctp_objs.filter.return_value = MagicMock(count=AsyncMock(return_value=1))

    with (
        patch.object(user, "has_model_perm", new=AsyncMock(return_value=False)),
        pytest.raises(PermissionError, match="Access denied 'delete'"),
    ):
        await check_permission_for_model(DummyAppModel, "delete")


@pytest.mark.asyncio
@patch("openviper.auth.models.ContentType.objects")
@patch("openviper.auth.models.ContentTypePermission.objects")
async def test_allow_sufficient_permissions(mock_ctp_objs, mock_ct_objs):
    """has_model_perm returns True → no error raised."""
    user = User(is_superuser=False)
    user.id = 1
    set_current_user(user)

    ct = ContentType(id=1, app_label="testapp", model="DummyAppModel")
    mock_ct_objs.filter.return_value = MagicMock(first=AsyncMock(return_value=ct))
    mock_ctp_objs.filter.return_value = MagicMock(count=AsyncMock(return_value=1))

    with patch.object(user, "has_model_perm", new=AsyncMock(return_value=True)):
        await check_permission_for_model(DummyAppModel, "write")
