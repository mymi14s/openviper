"""OpenViper built-in User, Role, and Permission models."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from openviper.auth._user_cache import invalidate_user_cache
from openviper.auth.hashers import check_password, make_password
from openviper.cache import InMemoryCache, get_cache
from openviper.conf import settings
from openviper.core.context import request_perms_cache
from openviper.db.events import _background_tasks, model_event
from openviper.db.fields import (
    BooleanField,
    CharField,
    DateTimeField,
    EmailField,
    ForeignKey,
    ManyToManyField,
    TextField,
)
from openviper.db.models import Model
from openviper.utils.importlib import import_string

logger = logging.getLogger("openviper.auth")


class Permission(Model):
    """A named permission grant."""

    _app_name = "auth"

    codename = CharField(max_length=100, unique=True)
    name = CharField(max_length=255)
    content_type = ForeignKey(to="auth.ContentType", on_delete="CASCADE", null=True, db_index=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        table_name = "auth_permissions"

    def __str__(self) -> str:
        return str(self.codename or "")


class Role(Model):
    """A named role bundling a set of permissions."""

    _app_name = "auth"

    name = CharField(max_length=100, unique=True)
    description = TextField(null=True)
    created_at = DateTimeField(auto_now_add=True)

    # ManyToMany relationship to permissions
    permissions = ManyToManyField(
        to="auth.Permission", through="auth.RolePermission", related_name="roles"
    )

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

    role_profile = ForeignKey(to="auth.RoleProfile", on_delete="CASCADE")
    role = ForeignKey(to="auth.Role", on_delete="CASCADE")
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        table_name = "auth_role_profile_details"

    def __str__(self) -> str:
        return f"{self.role_profile} - {self.role}"


class UserRole(Model):
    """Junction table linking users to roles."""

    _app_name = "auth"

    user = ForeignKey(to=settings.USER_MODEL)
    role = ForeignKey(to="auth.Role")

    class Meta:
        table_name = "auth_user_roles"

    def __str__(self) -> str:
        return f"{self.user} - {self.role}"


class RolePermission(Model):
    """Junction table linking roles to permissions."""

    _app_name = "auth"

    role = ForeignKey(to="auth.Role")
    permission = ForeignKey(to="auth.Permission")

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

    content_type = ForeignKey(to="auth.ContentType")
    role = ForeignKey(to="auth.Role")
    can_create = BooleanField(default=False)
    can_read = BooleanField(default=False)
    can_update = BooleanField(default=False)
    can_delete = BooleanField(default=False)

    class Meta:
        table_name = "auth_content_type_permissions"

    def __str__(self) -> str:
        return f"{self.content_type} - {self.role}"


class AbstractUser(Model):
    """Built-in user model with hashed passwords and permission management."""

    _app_name = "auth"

    username = CharField(max_length=150, unique=True)
    email = EmailField(unique=True)
    password = CharField(max_length=255, null=True)
    first_name = CharField(max_length=150, null=True)
    last_name = CharField(max_length=150, null=True)
    is_active = BooleanField(default=True, db_index=True)
    is_superuser = BooleanField(default=False, db_index=True)
    is_staff = BooleanField(default=False, db_index=True)
    role_profile = ForeignKey(to="auth.RoleProfile", null=True, blank=True, on_delete="CASCADE")
    created_at = DateTimeField(auto_now_add=True, editable=False)
    updated_at = DateTimeField(auto_now=True, editable=False)
    last_login = DateTimeField(null=True, editable=False)
    date_joined = DateTimeField(auto_now_add=True, editable=False)

    # ManyToMany relationship to roles
    roles = ManyToManyField(
        to="auth.Role", through="auth.UserRole", related_name="users", null=True, blank=True
    )

    class Meta:
        abstract = True

    _cached_perms: set[str]

    # ── Password methods ──────────────────────────────────────────────────

    async def set_password(self, raw_password: str) -> None:
        """Hash and store a password using Argon2id (bcrypt fallback)."""
        self.password = await make_password(raw_password)  # type: ignore[assignment]

    async def check_password(self, raw_password: str) -> bool:
        """Verify raw_password against stored hash."""
        if not self.password:
            return False
        return await check_password(raw_password, cast("str", self.password))

    # ── Permission and Role Methods ──────────────────────────────────────

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    async def get_roles(self) -> list[Role]:
        """Return all roles assigned to this user, respecting RoleProfile if set."""
        roles: list[Role] = []

        if self.role_profile:
            details = (
                await RoleProfileDetail.objects.filter(role_profile=self.role_profile)
                .select_related("role")
                .all()
            )
            ids_to_fetch: list[int] = []
            for detail in details:
                role_obj = detail.role  # type: ignore[attr-defined]
                if isinstance(role_obj, Role):
                    roles.append(role_obj)
                else:
                    ids_to_fetch.append(role_obj)
            if ids_to_fetch:
                fetched = await Role.objects.filter(id__in=ids_to_fetch).all()
                roles.extend(cast("list[Role]", fetched))
            return roles

        user_roles = await UserRole.objects.filter(user=self.pk).select_related("role").all()
        role_ids_to_fetch: list[int] = []
        for ur in user_roles:
            role_obj = ur.role  # type: ignore[attr-defined]
            if isinstance(role_obj, Role):
                roles.append(role_obj)
            else:
                role_ids_to_fetch.append(role_obj)
        if role_ids_to_fetch:
            fetched = await Role.objects.filter(id__in=role_ids_to_fetch).all()
            roles.extend(cast("list[Role]", fetched))
        return roles

    async def get_permissions(self) -> set[str]:
        """Fetch all permissions for this user from request cache, persistent cache, or DB."""
        req_cache = dict(request_perms_cache.get() or {})
        if self.pk in req_cache:
            return req_cache[self.pk]

        cache = get_cache()
        cache_key = f"user_perms:{self.pk}"
        cached_result = await cache.get(cache_key)
        if cached_result is not None:
            result_set = set(cached_result)
            req_cache[self.pk] = result_set
            request_perms_cache.set(req_cache)
            return result_set

        if self.is_superuser:
            perms = await Permission.objects.values_list("codename", flat=True)
            result_set = set(perms)
        else:
            roles = await self.get_roles()
            if not roles:
                result_set = set()
            else:
                role_ids = [r.pk for r in roles]
                role_perms = (
                    await RolePermission.objects.filter(role__in=role_ids)
                    .select_related("permission")
                    .all()
                )
                result_set = {rp.permission.codename for rp in role_perms}

        ttl = getattr(settings, "PERM_CACHE_TTL", 3600)
        if isinstance(cache, InMemoryCache):
            ttl = 60

        await cache.set(cache_key, list(result_set), ttl=ttl)
        req_cache[self.pk] = result_set
        request_perms_cache.set(req_cache)
        return result_set

    @property
    async def permissions(self) -> set[str]:
        return await self.get_permissions()

    async def has_perm(self, codename: str) -> bool:
        if self.is_superuser:
            return True
        perms = await self.get_permissions()
        return codename in perms

    async def has_model_perm(self, model_label: str, action: str) -> bool:
        """Check if user has a specific action permission for a model."""
        if self.is_superuser:
            return True

        action_field = f"can_{action}"
        roles = await self.get_roles()
        if not roles:
            return False

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
        if self.is_superuser:
            return True
        roles = await self.get_roles()
        return any(str(r.name) == role_name for r in roles)

    async def assign_role(self, role: Role) -> None:
        """Assign a role and clear caches for this user."""
        existing = await UserRole.objects.filter(user=self.pk, role=role.pk).first()
        if not existing:
            await UserRole.objects.create(user=self.pk, role=role.pk)
            cache = get_cache()
            await cache.delete(f"user_perms:{self.pk}")
            req_cache = dict(request_perms_cache.get() or {})
            if self.pk in req_cache:
                del req_cache[self.pk]
                request_perms_cache.set(req_cache)

    async def remove_role(self, role: Role) -> None:
        """Remove a role and clear caches for this user."""
        ur = await UserRole.objects.filter(user=self.pk, role=role.pk).first()
        if ur:
            await ur.delete()
        cache = get_cache()
        await cache.delete(f"user_perms:{self.pk}")
        req_cache = dict(request_perms_cache.get() or {})
        if self.pk in req_cache:
            del req_cache[self.pk]
            request_perms_cache.set(req_cache)

    @property
    def full_name(self) -> str:
        return " ".join(str(p) for p in [self.first_name, self.last_name] if p)

    def __str__(self) -> str:
        return str(self.username or self.pk)

    def __repr__(self) -> str:
        return f"<User id={self.pk!r} username={self.username!r}>"


class User(AbstractUser):
    """Concrete user model."""

    class Meta:
        table_name = "auth_users"
        abstract = getattr(settings, "USER_MODEL", None) != "openviper.auth.models.User"


class AnonymousUser:
    """Sentinel representing unauthenticated users."""

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


# ── Cache Helpers ──────────────────────────────────────────────────────


async def _reset_user_permission_cache(user_id: int) -> None:
    """Clear persistent and request caches for a single user."""
    cache = get_cache()
    await cache.delete(f"user_perms:{user_id}")
    req_cache = dict(request_perms_cache.get() or {})
    if user_id in req_cache:
        del req_cache[user_id]
        request_perms_cache.set(req_cache)
    logger.debug("Cleared permission cache for user %s", user_id)


async def _reset_all_superusers() -> None:
    """Reset caches for all superusers (they implicitly have all permissions)."""
    try:
        superusers = await UserModel.objects.filter(is_superuser=True).all()
        for user in superusers:
            await _reset_user_permission_cache(user.pk)
        logger.debug("Cleared permission caches for all superusers")
    except Exception as e:
        logger.warning("Failed to reset superuser caches: %s", e)


async def _reset_users_by_role(role_id: int) -> None:
    """Reset caches for all users assigned a given role."""
    user_roles = await UserRole.objects.filter(role=role_id).select_related("user").all()
    for ur in user_roles:
        uid = ur.user.pk  # type: ignore[attr-defined]
        await _reset_user_permission_cache(uid)


async def _reset_users_by_permission(permission_id: int) -> None:
    """Reset caches for users assigned roles linked to a specific permission."""
    role_perms = (
        await RolePermission.objects.filter(permission=permission_id).select_related("role").all()
    )
    for rp in role_perms:
        role_id = rp.role.pk  # type: ignore[attr-defined]
        await _reset_users_by_role(role_id)


async def _reset_users_by_content_type_permission(role_id: int) -> None:
    """Reset caches for all users assigned a role with ContentTypePermission."""
    await _reset_users_by_role(role_id)


# Dynamically resolve the active User model
UserModel = (
    import_string(settings.USER_MODEL)
    if settings.USER_MODEL != "openviper.auth.models.User"
    else User
)
# ── Event Handlers ─────────────────────────────────────────────────────


@model_event.trigger("openviper.auth.models.UserRole.after_insert")
@model_event.trigger("openviper.auth.models.UserRole.on_change")
@model_event.trigger("openviper.auth.models.UserRole.after_delete")
def _on_user_role_change(instance: Any, event: str | None = None, **kwargs: Any) -> None:
    """Reset permission caches for the user affected by a UserRole change."""
    user_id: Any = getattr(instance, "user", None)
    if hasattr(user_id, "pk"):
        user_id = user_id.pk
    if not user_id:
        logger.warning("UserRole change event received with no user_id — skipping cache reset.")
        return

    # Reset local request cache synchronously
    req_cache = dict(request_perms_cache.get() or {})
    if user_id in req_cache:
        del req_cache[user_id]
        request_perms_cache.set(req_cache)

    # Schedule global reset into tracked background tasks
    task = asyncio.create_task(_reset_user_permission_cache(user_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@model_event.trigger("openviper.auth.models.RolePermission.after_insert")
@model_event.trigger("openviper.auth.models.RolePermission.after_delete")
def _on_role_permission_change(instance: Any, event: str | None = None, **kwargs: Any) -> None:
    """Reset permission caches for all users affected by a RolePermission change."""
    role_id: Any = getattr(instance, "role", None)
    if hasattr(role_id, "pk"):
        role_id = role_id.pk

    # We clear the entire local cache for this context as role changes can affect many users
    request_perms_cache.set({})

    if role_id:
        task1 = asyncio.create_task(_reset_users_by_role(role_id))
        _background_tasks.add(task1)
        task1.add_done_callback(_background_tasks.discard)

    task2 = asyncio.create_task(_reset_all_superusers())
    _background_tasks.add(task2)
    task2.add_done_callback(_background_tasks.discard)


@model_event.trigger("openviper.auth.models.ContentTypePermission.after_insert")
@model_event.trigger("openviper.auth.models.ContentTypePermission.after_delete")
@model_event.trigger("openviper.auth.models.ContentTypePermission.on_update")
def _on_content_type_permission_change(
    instance: Any, event: str | None = None, **kwargs: Any
) -> None:
    """Reset permission caches for all users affected by a ContentTypePermission change."""
    role_id: Any = getattr(instance, "role", None)
    if hasattr(role_id, "pk"):
        role_id = role_id.pk

    request_perms_cache.set({})

    if role_id:
        task1 = asyncio.create_task(_reset_users_by_role(role_id))
        _background_tasks.add(task1)
        task1.add_done_callback(_background_tasks.discard)

    task2 = asyncio.create_task(_reset_all_superusers())
    _background_tasks.add(task2)
    task2.add_done_callback(_background_tasks.discard)


@model_event.trigger("openviper.auth.models.Permission.after_insert")
@model_event.trigger("openviper.auth.models.Permission.after_delete")
@model_event.trigger("openviper.auth.models.Permission.on_update")
def _on_permission_change(instance: Any, event: str | None = None, **kwargs: Any) -> None:
    """Reset permission caches for users of roles affected by a Permission change."""
    permission_id = getattr(instance, "pk", None)

    # Sync reset for local context
    request_perms_cache.set({})

    if permission_id:
        task1 = asyncio.create_task(_reset_users_by_permission(permission_id))
        _background_tasks.add(task1)
        task1.add_done_callback(_background_tasks.discard)

    task2 = asyncio.create_task(_reset_all_superusers())
    _background_tasks.add(task2)
    task2.add_done_callback(_background_tasks.discard)


@model_event.trigger("openviper.auth.models.Role.after_delete")
def _on_role_delete(instance: Any, event: str | None = None, **kwargs: Any) -> None:
    """Reset permission caches for users affected by a role deletion."""
    role_id = getattr(instance, "pk", None)
    # Sync reset for local context
    request_perms_cache.set({})
    if role_id:
        task1 = asyncio.create_task(_reset_users_by_role(role_id))
        _background_tasks.add(task1)
        task1.add_done_callback(_background_tasks.discard)
    task2 = asyncio.create_task(_reset_all_superusers())
    _background_tasks.add(task2)
    task2.add_done_callback(_background_tasks.discard)


@model_event.on_update(UserModel)
def _on_user_update(instance: Any, **kwargs: Any) -> None:
    """Evict the updated user from the in-process auth cache.

    Ensures that changes to fields such as ``is_active``, ``is_staff``, or
    ``password`` take effect on the next authenticated request without waiting
    for the 30-second TTL to expire naturally.
    """
    user_id = getattr(instance, "pk", None)
    if user_id:
        invalidate_user_cache(user_id)
