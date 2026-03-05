"""OpenViper built-in User, Role, and Permission models."""

from __future__ import annotations

from typing import cast

from openviper.auth.hashers import check_password, make_password
from openviper.conf import settings
from openviper.db.fields import (
    BooleanField,
    CharField,
    DateTimeField,
    EmailField,
    ForeignKey,
    TextField,
)
from openviper.db.models import Model

AUTH_USER = "openviper.auth.models.User"


class Permission(Model):
    """A named permission grant.

    Example::

        >>> perm = await Permission.objects.create(codename="post.create", name="Can create posts")
    """

    codename = CharField(max_length=100, unique=True)
    name = CharField(max_length=255)
    content_type = CharField(max_length=100, null=True)  # type: ignore[assignment]  # "app.Model"
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "auth_permissions"

    def __str__(self) -> str:
        return str(self.codename or "")


class Role(Model):
    """A named role that bundles a set of permissions.

    Example:
        >>> admin = await Role.objects.create(name="admin")
    """

    _app_name = "auth"

    name = CharField(max_length=100, unique=True)
    description = TextField(null=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "auth_roles"

    def __str__(self) -> str:
        return str(self.name or "")


class RoleProfile(Model):
    """Optional profile for Role to support hierarchical permissions."""

    _app_name = "auth"

    name = CharField(max_length=100, unique=True)
    description = TextField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        table_name = "auth_role_profiles"

    def __str__(self) -> str:
        return str(self.name)


class RoleProfileDetail(Model):
    """Details for RoleProfile to define hierarchical permissions."""

    _app_name = "auth"

    role_profile = ForeignKey(to="RoleProfile", on_delete="CASCADE")
    role = ForeignKey(to="Role", on_delete="CASCADE")
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        table_name = "auth_role_profile_details"

    def __str__(self) -> str:
        return f"{self.role_profile} - {self.role}"


class UserRole(Model):
    """Junction table between User and Role."""

    _app_name = "auth"

    user = ForeignKey(to="User" if settings.USER_MODEL == AUTH_USER else settings.USER_MODEL)
    role = ForeignKey(to="Role")

    class Meta:
        table_name = "auth_user_roles"

    def __str__(self) -> str:
        return f"{self.user} - {self.role}"


class RolePermission(Model):
    """Junction table between Role and Permission."""

    _app_name = "auth"

    role = ForeignKey(to="Role")
    permission = ForeignKey(to="Permission")

    class Meta:
        table_name = "auth_role_permissions"

    def __str__(self) -> str:
        return f"{self.role} - {self.permission}"


class ContentType(Model):
    """Registry of models for permissions."""

    _app_name = "auth"

    app_label = CharField(max_length=100)
    model = CharField(max_length=100)

    class Meta:
        table_name = "auth_content_types"

    def __str__(self) -> str:
        return f"{self.app_label}.{self.model}"


class ContentTypePermission(Model):
    """Granular permissions per content type for a role."""

    _app_name = "auth"

    content_type = ForeignKey(to="ContentType")  # type: ignore[assignment]
    role = ForeignKey(to="Role")
    can_create = BooleanField(default=False)
    can_read = BooleanField(default=False)
    can_update = BooleanField(default=False)
    can_delete = BooleanField(default=False)

    class Meta:
        table_name = "auth_content_type_permissions"

    def __str__(self) -> str:
        return f"{self.content_type} - {self.role}"


class AbstractUser(Model):
    """Built-in user model.

    Passwords are stored hashed via Argon2id (with bcrypt fallback).
    """

    _app_name = "auth"

    #: Unique login identifier.
    username = CharField(max_length=150, unique=True)
    #: Unique email address.
    email = EmailField(unique=True)
    #: Hashed password — never set this directly; use ``set_password()``.
    password = CharField(max_length=255, null=True)  # Hashed
    first_name = CharField(max_length=150, null=True)
    last_name = CharField(max_length=150, null=True)
    #: Soft-delete flag.
    is_active = BooleanField(default=True)
    #: Grant all permissions when True.
    is_superuser = BooleanField(default=False)
    #: Allow access to the admin interface.
    is_staff = BooleanField(default=False)
    role_profile = ForeignKey(to="RoleProfile", null=True, blank=True, on_delete="CASCADE")
    #: Account creation timestamp.
    created_at = DateTimeField(auto_now_add=True)
    #: Last modification timestamp.
    updated_at = DateTimeField(auto_now=True)
    #: Last successful login timestamp.
    last_login = DateTimeField(null=True)

    class Meta:
        abstract = True

    # Per-request permissions cache; populated lazily by get_permissions()
    _cached_perms: set[str]

    # ── Password methods ──────────────────────────────────────────────────

    def set_password(self, raw_password: str) -> None:
        """Hash and store a password.

        Uses Argon2id by default, falls back to bcrypt.
        """
        self.password = make_password(raw_password)  # type: ignore[assignment]

    def check_password(self, raw_password: str) -> bool:
        """Verify raw_password against the stored hash."""
        if not self.password:
            return False
        return check_password(raw_password, cast(str, self.password))

    # ── Permission checks ─────────────────────────────────────────────────

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    async def get_roles(self) -> list[Role]:
        """Return all roles for this user.

        If role_profile is set, returns the roles linked via RoleProfileDetail
        and ignores any directly assigned UserRoles.
        Otherwise falls back to roles assigned directly via UserRole.
        """
        if self.role_profile:
            details = await RoleProfileDetail.objects.filter(role_profile=self.role_profile).all()
            if not details:
                return []
            role_ids = [d.role for d in details]  # type: ignore[attr-defined]
            return await Role.objects.filter(id__in=role_ids).all()  # type: ignore[return-value]

        user_roles = await UserRole.objects.filter(user=self.pk).all()
        if not user_roles:
            return []
        role_ids = [ur.role for ur in user_roles]  # type: ignore[attr-defined]
        return await Role.objects.filter(id__in=role_ids).all()  # type: ignore[return-value]

    async def get_permissions(self) -> set[str]:
        """Return all permission codenames for this user (direct + via roles)."""
        # Per-request cache: user objects are created fresh per request, so
        # caching on the instance avoids repeated DB queries within one request.
        if hasattr(self, "_cached_perms"):
            return self._cached_perms

        if self.is_superuser:
            all_perms = await Permission.objects.filter().all()
            result: set[str] = {p.codename for p in all_perms}  # type: ignore[attr-defined]
            self._cached_perms = result
            return result

        roles = await self.get_roles()
        if not roles:
            self._cached_perms = set()
            return set()

        role_ids = [r.pk for r in roles]
        role_perms = await RolePermission.objects.filter(role__in=role_ids).all()
        perm_ids = [rp.permission for rp in role_perms]  # type: ignore[attr-defined]
        if not perm_ids:
            self._cached_perms = set()
            return set()

        perms = await Permission.objects.filter(id__in=perm_ids).all()
        result = {p.codename for p in perms}  # type: ignore[attr-defined]
        self._cached_perms = result
        return result

    async def has_perm(self, codename: str) -> bool:
        """Check if user has a specific permission by codename."""
        if self.is_superuser:
            return True
        perms = await self.get_permissions()
        return codename in perms

    async def has_model_perm(self, model_label: str, action: str) -> bool:
        """Check if user has a specific action permission for a model.

        Args:
            model_label: 'app_label.ModelName' or 'ModelName'
            action: 'create', 'read', 'write', 'update', 'delete'
        """
        if self.is_superuser:
            return True

        # Action normalization
        action_field = f"can_{action}"

        # 1. Check global roles
        roles = await self.get_roles()
        for role in roles:
            if getattr(role, action_field, False):
                return True

        # 2. Check ContentType specific permissions
        if "." in model_label:
            app_label, model_name = model_label.split(".", 1)
        else:
            app_label, model_name = "default", model_label

        content_type = await ContentType.objects.filter(
            app_label=app_label, model=model_name
        ).first()
        if not content_type:
            return False

        role_ids = [r.pk for r in roles]
        ct_perms = await ContentTypePermission.objects.filter(
            content_type=content_type.pk, role__in=role_ids
        ).all()

        return any(getattr(ctp, action_field, False) for ctp in ct_perms)

    async def has_role(self, role_name: str) -> bool:
        """Check if user is assigned to a specific role."""
        if self.is_superuser:
            return True
        roles = await self.get_roles()
        return any(str(r.name) == role_name for r in roles)

    async def assign_role(self, role: Role) -> None:
        """Assign a role to this user."""
        existing = await UserRole.objects.filter(user=self.pk, role=role.pk).first()
        if not existing:
            await UserRole.objects.create(user=self.pk, role=role.pk)

    async def remove_role(self, role: Role) -> None:
        """Remove a role from this user."""
        await UserRole.objects.filter(user=self.pk, role=role.pk).delete()

    @property
    def full_name(self) -> str:
        parts = [str(self.first_name or ""), str(self.last_name or "")]
        return " ".join(p for p in parts if p).strip()

    def __str__(self) -> str:
        return str(self.username or self.pk)

    def __repr__(self) -> str:
        return f"<User id={self.pk!r} username={self.username!r}>"


class User(AbstractUser):
    """User model for the platform."""

    class Meta:
        table_name = "auth_users"
        abstract = (
            getattr(settings, "USER_MODEL", getattr(settings, "AUTH_USER_MODEL", None)) != AUTH_USER
        )


class AnonymousUser:
    """Sentinel object representing an unauthenticated visitor."""

    is_authenticated: bool = False
    is_anonymous: bool = True
    is_active: bool = False
    is_superuser: bool = False
    is_staff: bool = False
    pk = None
    id = None
    username = ""
    email = ""

    async def has_perm(self, codename: str) -> bool:
        return False

    async def has_model_perm(self, model_label: str, action: str) -> bool:
        return False

    async def has_role(self, role_name: str) -> bool:
        return False

    async def get_permissions(self) -> set[str]:
        return set()

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "AnonymousUser"
