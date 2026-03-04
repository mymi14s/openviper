from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openviper.auth.models import (
    AnonymousUser,
    ContentType,
    ContentTypePermission,
    Permission,
    Role,
    RolePermission,
    RoleProfile,
    RoleProfileDetail,
    User,
    UserRole,
)


def test_permission_str():
    p = Permission(codename="test.code", name="Test")
    assert str(p) == "test.code"


def test_role_str():
    r = Role(name="admin")
    assert str(r) == "admin"


def test_user_properties():
    u = User(username="admin", email="admin@test.com", first_name="Admin", last_name="User")
    u.id = 1
    assert str(u) == "admin"
    assert repr(u) == "<User id=1 username='admin'>"
    assert u.full_name == "Admin User"

    assert u.is_authenticated is True
    assert u.is_anonymous is False


def test_user_passwords():
    u = User(username="admin")

    assert u.check_password("secret") is False  # No password set

    u.set_password("secret")
    assert u.password is not None
    assert u.check_password("secret") is True
    assert u.check_password("wrong") is False


# ── get_roles: UserRole fallback ──────────────────────────────────────────────


@pytest.mark.asyncio
@patch("openviper.auth.models.UserRole.objects")
@patch("openviper.auth.models.Role.objects")
async def test_user_get_roles(mock_role_objs, mock_ur_objs):
    u = User()
    u.id = 10

    ur_filter = MagicMock()
    mock_ur_objs.filter.return_value = ur_filter

    ur1 = UserRole(user_id=10, role_id=1)
    ur_filter.all = AsyncMock(return_value=[ur1])

    role_filter = MagicMock()
    mock_role_objs.filter.return_value = role_filter

    r1 = Role()
    r1.id = 1
    r1.name = "admin"
    role_filter.all = AsyncMock(return_value=[r1])

    roles = await u.get_roles()
    assert len(roles) == 1
    assert roles[0].name == "admin"
    mock_ur_objs.filter.assert_called_once_with(user=10)
    mock_role_objs.filter.assert_called_once_with(id__in=[1])


@pytest.mark.asyncio
async def test_user_get_roles_empty():
    u = User()
    u.id = 10

    with patch("openviper.auth.models.UserRole.objects") as mock_ur_objs:
        ur_filter = MagicMock()
        mock_ur_objs.filter.return_value = ur_filter
        ur_filter.all = AsyncMock(return_value=[])

        roles = await u.get_roles()
        assert roles == []


# ── get_roles: role_profile override ─────────────────────────────────────────


@pytest.mark.asyncio
@patch("openviper.auth.models.RoleProfileDetail.objects")
@patch("openviper.auth.models.Role.objects")
async def test_user_get_roles_via_role_profile(mock_role_objs, mock_rpd_objs):
    """When role_profile is set it overrides UserRole assignments."""
    u = User()
    u.id = 10
    u.role_profile = 3  # FK id of a RoleProfile

    rpd_filter = MagicMock()
    mock_rpd_objs.filter.return_value = rpd_filter

    detail = RoleProfileDetail()
    detail.role = 7  # FK id pointing to a Role
    rpd_filter.all = AsyncMock(return_value=[detail])

    role_filter = MagicMock()
    mock_role_objs.filter.return_value = role_filter

    r = Role()
    r.id = 7
    r.name = "editor"
    role_filter.all = AsyncMock(return_value=[r])

    roles = await u.get_roles()
    assert len(roles) == 1
    assert roles[0].name == "editor"
    mock_rpd_objs.filter.assert_called_once_with(role_profile=3)
    mock_role_objs.filter.assert_called_once_with(id__in=[7])


@pytest.mark.asyncio
@patch("openviper.auth.models.RoleProfileDetail.objects")
async def test_user_get_roles_via_role_profile_empty(mock_rpd_objs):
    """role_profile set but no RoleProfileDetail rows → empty roles."""
    u = User()
    u.id = 10
    u.role_profile = 3

    rpd_filter = MagicMock()
    mock_rpd_objs.filter.return_value = rpd_filter
    rpd_filter.all = AsyncMock(return_value=[])

    roles = await u.get_roles()
    assert roles == []


# ── permissions ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_get_permissions_superuser():
    u = User(is_superuser=True)

    with patch("openviper.auth.models.Permission.objects") as mock_perm_objs:
        mock_filter = MagicMock()
        mock_perm_objs.filter.return_value = mock_filter
        mock_filter.all = AsyncMock(
            return_value=[Permission(codename="p1"), Permission(codename="p2")]
        )

        perms = await u.get_permissions()
        assert perms == {"p1", "p2"}
        assert await u.has_perm("p1") is True
        assert await u.has_role("any") is True


@pytest.mark.asyncio
@patch("openviper.auth.models.User.get_roles")
@patch("openviper.auth.models.RolePermission.objects")
@patch("openviper.auth.models.Permission.objects")
async def test_user_get_permissions_normal(mock_perm_objs, mock_rp_objs, mock_get_roles):
    u = User(is_superuser=False)

    r = Role(name="editor")
    r.id = 5
    mock_get_roles.return_value = [r]

    assert await u.has_role("editor") is True
    assert await u.has_role("admin") is False

    rp_filter = MagicMock()
    mock_rp_objs.filter.return_value = rp_filter
    rp1 = RolePermission(role_id=5, permission_id=9)
    rp_filter.all = AsyncMock(return_value=[rp1])

    perm_filter = MagicMock()
    mock_perm_objs.filter.return_value = perm_filter
    p1 = Permission(codename="post.edit")
    perm_filter.all = AsyncMock(return_value=[p1])

    perms = await u.get_permissions()
    assert perms == {"post.edit"}
    assert await u.has_perm("post.edit") is True
    assert await u.has_perm("post.delete") is False


@pytest.mark.asyncio
@patch("openviper.auth.models.User.get_roles")
async def test_user_get_permissions_no_roles(mock_get_roles):
    u = User(is_superuser=False)
    mock_get_roles.return_value = []

    perms = await u.get_permissions()
    assert perms == set()


@pytest.mark.asyncio
@patch("openviper.auth.models.User.get_roles")
@patch("openviper.auth.models.RolePermission.objects")
async def test_user_get_permissions_no_perms(mock_rp_objs, mock_get_roles):
    u = User(is_superuser=False)
    r = Role(name="empty")
    r.id = 1
    mock_get_roles.return_value = [r]

    rp_filter = MagicMock()
    mock_rp_objs.filter.return_value = rp_filter
    rp_filter.all = AsyncMock(return_value=[])

    perms = await u.get_permissions()
    assert perms == set()


# ── assign / remove role ──────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("openviper.auth.models.UserRole.objects")
async def test_user_assign_remove_role(mock_ur_objs):
    u = User()
    u.id = 10
    r = Role()
    r.id = 2

    filter_mock = MagicMock()
    mock_ur_objs.filter.return_value = filter_mock
    filter_mock.first = AsyncMock(return_value=None)
    mock_ur_objs.create = AsyncMock()

    # Assign new
    await u.assign_role(r)
    mock_ur_objs.create.assert_called_once_with(user=10, role=2)

    # Assign existing (no-op)
    filter_mock.first = AsyncMock(return_value=UserRole())
    mock_ur_objs.create.reset_mock()
    await u.assign_role(r)
    mock_ur_objs.create.assert_not_called()

    # Remove
    filter_mock.delete = AsyncMock()
    await u.remove_role(r)
    filter_mock.delete.assert_called_once()


# ── AnonymousUser ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_anonymous_user():
    anon = AnonymousUser()
    assert anon.is_authenticated is False
    assert anon.is_anonymous is True
    assert anon.is_active is False
    assert anon.is_superuser is False
    assert anon.is_staff is False
    assert bool(anon) is False
    assert repr(anon) == "AnonymousUser"

    assert await anon.has_perm("any") is False
    assert await anon.has_role("any") is False
    assert await anon.get_permissions() == set()


# ── __str__ on secondary models ───────────────────────────────────────────────


def test_role_profile_str():
    rp = RoleProfile(name="editors")
    assert str(rp) == "editors"


def test_content_type_str():
    ct = ContentType(app_label="blog", model="Post")
    assert str(ct) == "blog.Post"


def test_role_profile_detail_str():
    rp = RoleProfile(name="Profile1")
    r = Role(name="Role1")
    rpd = RoleProfileDetail()
    rpd.role_profile = rp
    rpd.role = r
    result = str(rpd)
    assert "Profile1" in result
    assert "Role1" in result


def test_user_role_str():
    r = Role(name="admin")
    ur = UserRole()
    ur.user = "alice"
    ur.role = r
    result = str(ur)
    assert "alice" in result
    assert "admin" in result


def test_role_permission_str():
    r = Role(name="editor")
    p = Permission(codename="post.write", name="Write Post")
    rp = RolePermission()
    rp.role = r
    rp.permission = p
    result = str(rp)
    assert "editor" in result
    assert "post.write" in result


def test_content_type_permission_str():
    ct = ContentType(app_label="blog", model="Post")
    r = Role(name="admin")
    ctp = ContentTypePermission()
    ctp.content_type = ct
    ctp.role = r
    result = str(ctp)
    assert "blog.Post" in result
    assert "admin" in result


# ── has_model_perm ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_has_model_perm_superuser():
    """Superuser always gets True regardless of model/action."""
    u = User(is_superuser=True)
    assert await u.has_model_perm("blog.Post", "read") is True


@pytest.mark.asyncio
async def test_has_model_perm_role_grants_action():
    """A role with can_read=True grants the permission without checking ContentType."""
    u = User(is_superuser=False)
    r = Role(name="reader")
    r.can_read = True
    u.get_roles = AsyncMock(return_value=[r])

    assert await u.has_model_perm("blog.Post", "read") is True


@pytest.mark.asyncio
@patch("openviper.auth.models.ContentType.objects")
@patch("openviper.auth.models.User.get_roles")
async def test_has_model_perm_no_content_type(mock_get_roles, mock_ct_objs):
    """Returns False when no ContentType matches the model label."""
    u = User(is_superuser=False)
    r = Role(name="viewer")
    r.can_read = False
    mock_get_roles.return_value = [r]

    ct_filter = MagicMock()
    mock_ct_objs.filter.return_value = ct_filter
    ct_filter.first = AsyncMock(return_value=None)

    assert await u.has_model_perm("blog.Post", "read") is False


@pytest.mark.asyncio
@patch("openviper.auth.models.ContentTypePermission.objects")
@patch("openviper.auth.models.ContentType.objects")
@patch("openviper.auth.models.User.get_roles")
async def test_has_model_perm_content_type_permission_grants(
    mock_get_roles, mock_ct_objs, mock_ctp_objs
):
    """Returns True when a ContentTypePermission row grants the action."""
    u = User(is_superuser=False)
    r = Role(name="viewer")
    r.can_read = False
    r.id = 7
    mock_get_roles.return_value = [r]

    ct = ContentType(app_label="blog", model="Post")
    ct.id = 1
    ct_filter = MagicMock()
    mock_ct_objs.filter.return_value = ct_filter
    ct_filter.first = AsyncMock(return_value=ct)

    ctp = ContentTypePermission()
    ctp.can_read = True
    ctp_filter = MagicMock()
    mock_ctp_objs.filter.return_value = ctp_filter
    ctp_filter.all = AsyncMock(return_value=[ctp])

    assert await u.has_model_perm("blog.Post", "read") is True


@pytest.mark.asyncio
@patch("openviper.auth.models.ContentTypePermission.objects")
@patch("openviper.auth.models.ContentType.objects")
@patch("openviper.auth.models.User.get_roles")
async def test_has_model_perm_dotless_label(mock_get_roles, mock_ct_objs, mock_ctp_objs):
    """A model label without a dot uses 'default' as app_label."""
    u = User(is_superuser=False)
    r = Role(name="viewer")
    r.can_delete = False
    r.id = 5
    mock_get_roles.return_value = [r]

    ct = ContentType(app_label="default", model="Post")
    ct.id = 2
    ct_filter = MagicMock()
    mock_ct_objs.filter.return_value = ct_filter
    ct_filter.first = AsyncMock(return_value=ct)

    ctp_filter = MagicMock()
    mock_ctp_objs.filter.return_value = ctp_filter
    ctp_filter.all = AsyncMock(return_value=[])

    result = await u.has_model_perm("Post", "delete")
    assert result is False
    # Verify the filter used "default" as app_label
    mock_ct_objs.filter.assert_called_once_with(app_label="default", model="Post")
