"""Admin API REST endpoints.

Provides CRUD operations, search, filtering, and batch actions
for all admin-registered models.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import datetime
import io
import json
import logging
import re
import typing as t
import uuid
from typing import TYPE_CHECKING

import sqlalchemy.exc

from openviper.admin.actions import ActionResult, get_action
from openviper.admin.api.permissions import check_admin_access, check_model_permission
from openviper.admin.fields import coerce_field_value, get_field_component_type, get_filter_choices
from openviper.admin.history import (
    ChangeAction,
    compute_changes,
    get_change_history,
    get_recent_activity,
    log_change,
)
from openviper.admin.registry import NotRegistered, admin
from openviper.auth import authenticate, create_access_token, create_refresh_token, get_user_model
from openviper.auth.jwt import decode_refresh_token, decode_token_unverified
from openviper.auth.token_blocklist import is_token_revoked, revoke_token
from openviper.conf import settings
from openviper.db.backends.registry import backend_registry
from openviper.db.exceptions import VirtualBackendNotFoundError
from openviper.db.fields import ManyToManyField
from openviper.db.queryspec import QuerySpec
from openviper.db.utils import cast_to_pk_type
from openviper.exceptions import NotFound, PermissionDenied, Unauthorized, ValidationError
from openviper.http.response import JSONResponse, Response
from openviper.middleware.ratelimit import rate_limit
from openviper.routing.router import Router
from openviper.utils import timezone

if TYPE_CHECKING:
    from openviper.admin import ModelAdmin
    from openviper.db import Model
    from openviper.http.request import Request

CSV_INJECTION_PREFIXES: frozenset[str] = frozenset({"=", "+", "-", "@", "\t", "\r"})


def sanitize_csv_cell(value: t.Any) -> str:
    """Sanitize a cell value for safe CSV export.

    Prevents CSV/Formula injection by prefixing dangerous leading characters
    with a single quote, which forces spreadsheet applications to treat the
    cell as plain text.
    """
    text = "" if value is None else str(value)
    if text and text[0] in CSV_INJECTION_PREFIXES:
        return f"'{text}"
    return text


def sanitize_filename(name: str) -> str:
    """Sanitize a model name for safe use in Content-Disposition filenames.

    Strips characters that could break header formatting (quotes, newlines,
    backslashes) and replaces non-alphanumeric runs with underscores.
    """
    sanitized = re.sub(r"""[\\"\r\n]""", "", name)
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", sanitized)
    return sanitized or "export"


User = get_user_model()
logger = logging.getLogger(__name__)


def is_auth_user_model(model_class: type) -> bool:
    """Check if a model class is the AUTH_USER_MODEL.

    Args:
        model_class: The model class to check.

    Returns:
        True if the model is the AUTH_USER_MODEL (or extends it).
    """
    try:
        _User = get_user_model()
        return model_class is _User or issubclass(model_class, _User)
    except Exception:
        logger.debug("_is_user_model check failed for %s", model_class, exc_info=True)
        return False


def row_has_meaningful_child_data(row: dict[str, t.Any], fk_name: str) -> bool:
    """Return True when a child-table row has at least one non-empty editable value."""
    for key, value in row.items():
        if key in {"id", fk_name}:
            continue
        if value not in (None, "", [], {}, ()):
            return True
    return False


async def batch_load_children(
    model_admin: ModelAdmin, model_class: type[Model], instances: list[Model]
) -> dict[int, dict[str, list[dict[str, t.Any]]]]:
    """Batch load child table data for multiple instances.

    Args:
        model_admin: The model admin configuration.
        model_class: The parent model class.
        instances: List of parent instances.

    Returns:
        Dict mapping instance ID to child table data.
    """
    if not instances:
        return {}

    instance_ids = [inst.id for inst in instances]
    children_by_instance: dict[int, dict[str, list[dict[str, t.Any]]]] = {
        inst_id: {} for inst_id in instance_ids
    }

    for inline_class in model_admin.child_tables or model_admin.inlines:
        inline = inline_class(model_class)
        child_model = inline.model
        fk_name = inline.fk_name

        child_fields = getattr(child_model, "_fields", {})

        if not fk_name:
            for name, f in child_fields.items():
                if (
                    f.__class__.__name__ in ("ForeignKey", "OneToOneField")
                    and f.resolve_target() == model_class
                ):
                    fk_name = name
                    break

        if not fk_name:
            continue

        fk_field = child_fields.get(fk_name) if fk_name else None
        fk_col = fk_field.column_name if fk_field and hasattr(fk_field, "column_name") else fk_name
        filters = {f"{fk_col}__in": instance_ids}
        if hasattr(inline, "extra_filters") and inline.extra_filters:
            filters.update({str(k): v for k, v in inline.extra_filters.items()})

        all_child_records = await child_model.objects.filter(**filters).all()

        child_fields_list = inline.fields or list(getattr(child_model, "_fields", {}).keys())
        related_name = child_model.__name__.lower() + "_set"

        for child in all_child_records:
            parent_id = getattr(child, fk_col, None)
            if parent_id is None and fk_name != fk_col:
                parent_id = getattr(child, fk_name, None)
                if parent_id is not None and hasattr(parent_id, "id"):
                    parent_id = parent_id.id
            if parent_id in children_by_instance:
                child_data = {"id": child.id}
                for f_name in child_fields_list:
                    val = getattr(child, f_name, None)
                    if hasattr(val, "isoformat"):
                        val = val.isoformat()
                    elif val is not None and not isinstance(
                        val, (str, int, float, bool, list, dict)
                    ):
                        val = str(val)
                    child_data[f_name] = val

                if related_name not in children_by_instance[parent_id]:
                    children_by_instance[parent_id][related_name] = []
                children_by_instance[parent_id][related_name].append(child_data)

    return children_by_instance


def parse_unique_violation_fields(exc: sqlalchemy.exc.IntegrityError) -> dict[str, str | None]:
    """Parse a unique-violation IntegrityError and return the conflicting column→value map."""
    orig_str = str(exc.orig) if hasattr(exc, "orig") and exc.orig else str(exc)
    pg_match = re.search(r"Key \(([^)]+)\)=\(([^)]*)\) already exists", orig_str)
    if pg_match:
        col_names = [c.strip() for c in pg_match.group(1).split(",")]
        col_values = [v.strip() for v in pg_match.group(2).split(",")]
        return dict(zip(col_names, col_values, strict=False))
    sqlite_match = re.search(r"UNIQUE constraint failed: \w+\.(\w+)", orig_str)
    if sqlite_match:
        return {sqlite_match.group(1): None}
    return {}


async def find_existing_on_unique_violation(
    model_class: type[t.Any],
    exc: sqlalchemy.exc.IntegrityError,
    coerced_data: dict[str, t.Any],
) -> int | str | None:
    """Return the PK of the conflicting record, or None if it cannot be determined."""
    parsed = parse_unique_violation_fields(exc)
    if not parsed:
        return None
    model_fields = getattr(model_class, "_fields", {})
    filter_kwargs: dict[str, t.Any] = {}
    for col_name, col_value in parsed.items():
        if col_name not in model_fields:
            continue
        if col_name in coerced_data:
            filter_kwargs[col_name] = coerced_data[col_name]
        elif col_value is not None:
            filter_kwargs[col_name] = col_value
    if not filter_kwargs:
        return None
    with contextlib.suppress(Exception):
        existing = await model_class.objects.filter(**filter_kwargs).first()
        if existing:
            return existing.id
    return None


async def serialize_instance_with_children(
    request: Request,
    model_admin: ModelAdmin,
    model_class: type[Model],
    instance: Model,
    preloaded_children: dict[str, list[dict[str, t.Any]]] | None = None,
) -> dict[str, t.Any]:
    """Helper to serialize an instance with its child table data.

    Args:
        request: The current request.
        model_admin: The model admin configuration.
        model_class: The model class.
        instance: The instance to serialize.
        preloaded_children: Optional preloaded children data to avoid N+1 queries.

    Returns:
        Serialized instance data with children.
    """
    sensitive_fields = model_admin.get_sensitive_fields()
    fields = getattr(model_class, "_fields", {})

    response_data = {"id": instance.id}
    for field_name, field_obj in fields.items():
        if field_name in sensitive_fields:
            continue
        if isinstance(field_obj, ManyToManyField):
            continue
        value = getattr(instance, field_name, None)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        elif value is not None and not isinstance(value, (str, int, float, bool, list, dict)):
            value = str(value)
        response_data[field_name] = value

    if preloaded_children is not None:
        response_data.update(preloaded_children)
    else:
        for inline_class in model_admin.child_tables or model_admin.inlines:
            inline = inline_class(model_class)
            child_model = inline.model
            fk_name = inline.fk_name

            if not fk_name:
                child_fields = getattr(child_model, "_fields", {})
                for name, f in child_fields.items():
                    if (
                        f.__class__.__name__ in ("ForeignKey", "OneToOneField")
                        and f.resolve_target() == model_class
                    ):
                        fk_name = name
                        break

            if fk_name:
                filters = {str(fk_name): instance.id}
                if hasattr(inline, "extra_filters") and inline.extra_filters:
                    filters.update({str(k): v for k, v in inline.extra_filters.items()})

                child_qs = child_model.objects.filter(**filters)
                child_records = await child_qs.all()

                serialized_children = []
                child_fields_list = inline.fields or list(
                    getattr(child_model, "_fields", {}).keys()
                )
                for child in child_records:
                    child_data = {"id": child.id}
                    for f_name in child_fields_list:
                        val = getattr(child, f_name, None)
                        if hasattr(val, "isoformat"):
                            val = val.isoformat()
                        elif val is not None and not isinstance(
                            val, (str, int, float, bool, list, dict)
                        ):
                            val = str(val)
                        child_data[f_name] = val
                    serialized_children.append(child_data)

                response_data[child_model.__name__.lower() + "_set"] = serialized_children

    return response_data


def get_admin_router() -> Router:
    """Create and return the admin API router.

    Returns:
        Router with all admin API endpoints.
    """
    router = Router()

    @router.get("/config/")
    async def admin_config(request: Request) -> JSONResponse:
        """Get UI configuration settings for the admin panel."""
        user_model = User
        user_model_string = f"{user_model._app_name}.{user_model.__name__}"

        return JSONResponse(
            {
                "admin_title": getattr(settings, "ADMIN_TITLE", "OpenViper Admin"),
                "admin_header_title": getattr(settings, "ADMIN_HEADER_TITLE", "OpenViper"),
                "admin_footer_title": getattr(settings, "ADMIN_FOOTER_TITLE", "OpenViper Admin"),
                "user_model": user_model_string,
                "auth_user_model": user_model_string,
                "is_custom_user": getattr(
                    settings, "USER_MODEL", getattr(settings, "AUTH_USER_MODEL", None)
                )
                is not None,
            }
        )

    @router.post("/auth/login/")
    @rate_limit(max_requests=5, window_seconds=60)
    async def admin_login(request: Request) -> JSONResponse:
        """Login to admin panel.

        Request body:
            username: str
            password: str

        Returns:
            JWT tokens and user info.
        """
        data = await request.json()
        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            raise ValidationError({"detail": "Username and password are required."})

        try:
            user = await authenticate(username=username, password=password)
        except Exception as exc:
            detail = getattr(exc, "detail", None) or "Invalid username or password."
            raise Unauthorized(detail) from exc

        if not getattr(user, "is_staff", False) and not getattr(user, "is_superuser", False):
            raise PermissionDenied("Admin access requires staff privileges.")

        access_token = create_access_token(
            user.id, {"username": user.username}, expires_delta=datetime.timedelta(hours=24)
        )
        refresh_token = create_refresh_token(user.id)

        return JSONResponse(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": getattr(user, "email", ""),
                    "is_staff": getattr(user, "is_staff", False),
                    "is_superuser": getattr(user, "is_superuser", False),
                },
            }
        )

    @router.post("/auth/logout/")
    async def admin_logout(request: Request) -> JSONResponse:
        """Logout from admin panel.

        Revokes the access token (from the Authorization header) and the
        refresh token (from the request body, if provided) so they cannot
        be used again even before their natural expiry.
        """
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            access_token = auth_header[7:]
            claims = decode_token_unverified(access_token)
            jti = claims.get("jti")
            if jti:
                exp = claims.get("exp", 0)
                expires_at = datetime.datetime.fromtimestamp(exp, tz=datetime.UTC)
                user_id = claims.get("sub")
                with contextlib.suppress(Exception):
                    await revoke_token(
                        jti=jti,
                        token_type="access",
                        user_id=user_id or None,
                        expires_at=expires_at,
                    )

        try:
            body = await request.json()
            refresh_token = body.get("refresh_token")
        except Exception:
            logger.debug("Failed to parse request body for refresh token revocation")
            refresh_token = None

        if refresh_token:
            claims = decode_token_unverified(refresh_token)
            jti = claims.get("jti")
            if jti:
                exp = claims.get("exp", 0)
                expires_at = datetime.datetime.fromtimestamp(exp, tz=datetime.UTC)
                user_id = claims.get("sub")
                with contextlib.suppress(Exception):
                    await revoke_token(
                        jti=jti,
                        token_type="refresh",
                        user_id=user_id or None,
                        expires_at=expires_at,
                    )

        return JSONResponse({"detail": "Logged out successfully."})

    @router.post("/auth/refresh/")
    async def admin_refresh_token(request: Request) -> JSONResponse:
        """Refresh access token.

        Request body:
            refresh_token: str

        Returns:
            New access token.
        """
        data = await request.json()
        refresh_token = data.get("refresh_token")

        if not refresh_token:
            raise ValidationError({"detail": "Refresh token is required."})

        try:
            payload = decode_refresh_token(refresh_token)
            user_id = payload.get("sub")
        except Exception as exc:
            raise ValidationError({"detail": "Invalid refresh token."}) from exc

        jti = payload.get("jti")
        if jti and await is_token_revoked(jti):
            raise ValidationError({"detail": "Refresh token has been revoked."})

        user_cls = User
        user_id_casted = cast_to_pk_type(user_cls, user_id)
        user = await user_cls.objects.get_or_none(id=user_id_casted)
        if not user:
            raise ValidationError({"detail": "User not found."})

        expires_at = timezone.now() + datetime.timedelta(hours=24)
        access_token = create_access_token(
            user.id, {"username": user.username}, expires_delta=datetime.timedelta(hours=24)
        )

        return JSONResponse(
            {
                "token": access_token,
                "access_token": access_token,
                "expires_at": expires_at.isoformat(),
            }
        )

    @router.get("/auth/me/")
    async def admin_current_user(request: Request) -> JSONResponse:
        """Get current authenticated user."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        user = request.user
        return JSONResponse(
            {
                "id": user.id,
                "username": user.username,
                "email": getattr(user, "email", ""),
                "is_staff": getattr(user, "is_staff", False),
                "is_superuser": getattr(user, "is_superuser", False),
            }
        )

    @router.post("/auth/change-password/")
    @rate_limit(max_requests=5, window_seconds=60)
    async def admin_change_password(request: Request) -> JSONResponse:
        """Change password for the current authenticated user.

        Request body:
            current_password: str
            new_password: str
            confirm_password: str

        Returns:
            Success message.
        """
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        data = await request.json()
        current_password = data.get("current_password")
        new_password = data.get("new_password")
        confirm_password = data.get("confirm_password")

        if not current_password or not new_password:
            raise ValidationError({"detail": "Current and new password are required."})

        if new_password != confirm_password:
            raise ValidationError({"detail": "New passwords do not match."})

        if len(new_password) < 8:
            raise ValidationError({"detail": "Password must be at least 8 characters."})

        user_cls = User
        user_id_casted = cast_to_pk_type(user_cls, request.user.id)
        user = await user_cls.objects.get_or_none(id=user_id_casted)
        if not user:
            raise NotFound("User not found.")

        if not await user.check_password(current_password):
            raise ValidationError({"detail": "Current password is incorrect."})

        await user.set_password(new_password)
        await user.save()

        return JSONResponse({"detail": "Password changed successfully."})

    @router.post("/auth/change-user-password/{user_id}/")
    @rate_limit(max_requests=5, window_seconds=60)
    async def admin_change_user_password(request: Request, user_id: str) -> JSONResponse:
        """Change password for a specific user (admin only).

        Request body:
            new_password: str
            confirm_password: str

        Returns:
            Success message.
        """
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        if not request.user.is_superuser:
            raise PermissionDenied("Only superusers can change other users' passwords.")

        data = await request.json()
        new_password = data.get("new_password")
        confirm_password = data.get("confirm_password")

        if not new_password:
            raise ValidationError({"detail": "New password is required."})

        if new_password != confirm_password:
            raise ValidationError({"detail": "Passwords do not match."})

        if len(new_password) < 8:
            raise ValidationError({"detail": "Password must be at least 8 characters."})

        user_cls = User
        user_id_casted = cast_to_pk_type(user_cls, user_id)
        user = await user_cls.objects.get_or_none(id=user_id_casted)
        if not user:
            raise NotFound("User not found.")

        await user.set_password(new_password)
        await user.save()

        return JSONResponse({"detail": f"Password changed successfully for {user.username}."})

    @router.get("/dashboard/")
    async def admin_dashboard(request: Request) -> JSONResponse:
        """Get dashboard statistics and recent activity."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        all_models = admin.get_all_models()

        async def get_model_count(model_class: type[Model], model_name: str) -> tuple[str, int]:
            """Get count for a single model."""
            try:
                count = await model_class.objects.count()
                return (model_name, count)
            except Exception:
                logger.warning("Failed to count %s, defaulting to 0", model_name, exc_info=True)
                return (model_name, 0)

        count_tasks = [
            get_model_count(model_class, model_class.__name__) for model_class, _ in all_models
        ]
        count_results = await asyncio.gather(*count_tasks)
        stats = dict(count_results)

        recent_activity = []
        try:
            activity_records = await get_recent_activity(limit=10)
            for record in activity_records:
                recent_activity.append(
                    {
                        "id": record.id,
                        "model_name": record.model_name,
                        "object_id": record.object_id,
                        "object_repr": record.object_repr,
                        "action": record.action,
                        "changed_by": record.changed_by_username,
                        "change_time": (
                            record.change_time.isoformat() if record.change_time else None
                        ),
                    }
                )
        except Exception:
            logger.debug("Failed to load change history, table may not exist yet", exc_info=True)

        return JSONResponse(
            {
                "stats": stats,
                "recent_activity": recent_activity,
                "models_count": len(stats),
            }
        )

    @router.get("/models/")
    async def list_models(request: Request) -> JSONResponse:
        """List all registered models with their admin configuration."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        models = []
        for model_class, model_admin in admin.get_all_models():
            if check_model_permission(request, model_class, "view"):
                models.append(model_admin.get_model_info(request))

        grouped = admin.get_models_grouped_by_app()
        apps = []
        for app_name, model_list in grouped.items():
            app_models = []
            for model_class, _ in model_list:
                if check_model_permission(request, model_class, "view"):
                    app_models.append(
                        {
                            "name": model_class.__name__,
                            "verbose_name": model_class.__name__,
                        }
                    )
            if app_models:
                apps.append({"name": app_name, "models": app_models})

        return JSONResponse(
            {
                "models": models,
                "apps": apps,
            }
        )

    @router.get("/models/{app_label}/{model_name}/")
    async def get_model_config(request: Request, app_label: str, model_name: str) -> JSONResponse:
        """Get model configuration and metadata."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_app_and_name(app_label, model_name)
            model_class = admin.get_model_by_app_and_name(app_label, model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{app_label}/{model_name}' not found.") from exc

        if not check_model_permission(request, model_class, "view"):
            raise PermissionDenied(f"No permission to view {model_name}.")

        return JSONResponse(model_admin.get_model_info(request))

    @router.get("/models/{app_label}/{model_name}/single/")
    async def get_single_instance(
        request: Request, app_label: str, model_name: str
    ) -> JSONResponse:
        """Get the single instance for a singleton model."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_app_and_name(app_label, model_name)
            model_class = admin.get_model_by_app_and_name(app_label, model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{app_label}/{model_name}' not found.") from exc

        if not getattr(model_class, "_meta", None) or not model_class._meta.single:
            raise NotFound(f"Model '{app_label}/{model_name}' is not a singleton model.")

        if not check_model_permission(request, model_class, "view"):
            raise PermissionDenied(f"No permission to view {model_name}.")

        instance = await model_class.objects.filter(ignore_permissions=True).first()
        if not instance:
            raise NotFound(f"No {model_name} instance found.")

        if not model_admin.has_view_permission(request, instance):
            raise PermissionDenied(f"No permission to view this {model_name}.")

        response_data = await serialize_instance_with_children(
            request, model_admin, model_class, instance
        )
        model_info = model_admin.get_model_info(request)

        return JSONResponse(
            {
                "instance": response_data,
                "model_info": model_info,
                "readonly_fields": model_admin.get_readonly_fields(request, instance),
                "fieldsets": model_admin.get_fieldsets(request, instance),
            }
        )

    @router.put("/models/{app_label}/{model_name}/single/")
    async def update_single_instance(
        request: Request, app_label: str, model_name: str
    ) -> JSONResponse:
        """Update the single instance for a singleton model."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_app_and_name(app_label, model_name)
            model_class = admin.get_model_by_app_and_name(app_label, model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{app_label}/{model_name}' not found.") from exc

        if not getattr(model_class, "_meta", None) or not model_class._meta.single:
            raise NotFound(f"Model '{app_label}/{model_name}' is not a singleton model.")

        instance = await model_class.objects.filter(ignore_permissions=True).first()
        if not instance:
            raise NotFound(f"No {model_name} instance found.")

        if not model_admin.has_change_permission(request, instance):
            raise PermissionDenied(f"No permission to change {model_name}.")

        if "multipart/form-data" in request.headers.get("content-type", ""):
            form = await request.form()
            data: dict[str, t.Any] = {}
            for k, v in form.items():
                if isinstance(v, str) and (v.startswith("[") or v.startswith("{")):
                    try:
                        data[k] = json.loads(v)
                    except json.JSONDecodeError:
                        data[k] = v
                else:
                    data[k] = v
        else:
            data = await request.json()

        fields = getattr(model_class, "_fields", {})
        old_data: dict[str, t.Any] = {}
        for field_name, field_obj in fields.items():
            if isinstance(field_obj, ManyToManyField):
                continue
            old_data[field_name] = getattr(instance, field_name, None)

        readonly_fields = model_admin.get_readonly_fields(request, instance)
        excluded_fields = set(model_admin.get_exclude(request, instance))
        sensitive_fields = set(model_admin.get_sensitive_fields(request, instance))
        new_data: dict[str, t.Any] = {}
        field_errors: dict[str, str] = {}

        for field_name, value in data.items():
            if field_name in readonly_fields:
                continue
            if field_name in excluded_fields or field_name in sensitive_fields:
                continue
            try:
                if field_name in fields:
                    if isinstance(fields[field_name], ManyToManyField):
                        continue
                    coerced_value = coerce_field_value(fields[field_name], value)
                    setattr(instance, field_name, coerced_value)
                    new_data[field_name] = coerced_value
                else:
                    continue
            except ValueError as exc:
                field_errors[field_name] = str(exc)

        if field_errors:
            return JSONResponse({"errors": field_errors}, status_code=422)

        await instance.save(ignore_permissions=True)

        changes = compute_changes(old_data, new_data)
        if changes:
            asyncio.create_task(
                log_change(
                    model_name=f"{app_label}.{model_name}",
                    object_id=instance.id,
                    action=ChangeAction.CHANGE,
                    changes=changes,
                    user=request.user,
                    object_repr=str(instance),
                )
            )

        response_data = await serialize_instance_with_children(
            request, model_admin, model_class, instance
        )

        return JSONResponse({"instance": response_data})

    @router.get("/models/{app_label}/{model_name}/list/")
    async def list_instances_by_app(
        request: Request, app_label: str, model_name: str
    ) -> JSONResponse:
        """List instances of a model with pagination, search, and filtering."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_app_and_name(app_label, model_name)
            model_class = admin.get_model_by_app_and_name(app_label, model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{app_label}/{model_name}' not found.") from exc

        if not check_model_permission(request, model_class, "view"):
            try:
                page = max(1, int(request.query_params.get("page", 1)))
            except ValueError, TypeError:
                page = 1
            try:
                per_page = max(
                    1,
                    int(
                        request.query_params.get(
                            "per_page",
                            request.query_params.get("page_size", model_admin.list_per_page),
                        )
                    ),
                )
            except ValueError, TypeError:
                per_page = model_admin.list_per_page
            return JSONResponse(
                {
                    "items": [],
                    "total": 0,
                    "page": page,
                    "per_page": per_page,
                    "total_pages": 0,
                    "list_display": model_admin.get_list_display(request),
                    "permission_denied": True,
                    "permission_message": f"You do not have permission to view {model_name}.",
                }
            )

        model_opts = getattr(model_class, "_meta", None)
        if model_opts is not None and getattr(model_opts, "virtual", False) is True:
            try:
                backend = backend_registry.get(model_class._meta.backend)
            except VirtualBackendNotFoundError as exc:
                raise NotFound(
                    f"Virtual backend '{model_class._meta.backend}' for "
                    f"'{app_label}/{model_name}' is not registered."
                ) from exc

            query_filters: dict[str, object] = {}
            model_fields = getattr(model_class, "_fields", {})
            allowed_fields = set(model_fields.keys())
            for key, value in request.query_params.items():
                if key.startswith("filter_"):
                    field_name = key[7:]
                    if field_name in allowed_fields:
                        query_filters[field_name] = value

            search_query = request.query_params.get(
                "search", request.query_params.get("q", "")
            ).strip()
            if search_query:
                search_fields = model_admin.get_search_fields(request)
                for sf in search_fields:
                    if sf in allowed_fields:
                        query_filters[sf] = search_query
                        break

            sort_field = request.query_params.get("ordering", request.query_params.get("sort", ""))
            order_by: list[str] | None = None
            if sort_field:
                bare_field = sort_field.lstrip("-")
                if bare_field in allowed_fields:
                    order_by = [sort_field]
            else:
                admin_ordering = model_admin.get_ordering(request)
                if admin_ordering:
                    order_by = list(admin_ordering)

            try:
                page = max(1, int(request.query_params.get("page", 1)))
            except ValueError, TypeError:
                page = 1
            try:
                page_size = min(
                    1000,
                    max(
                        1,
                        int(
                            request.query_params.get(
                                "per_page",
                                request.query_params.get("page_size", model_admin.list_per_page),
                            )
                        ),
                    ),
                )
            except ValueError, TypeError:
                page_size = model_admin.list_per_page
            offset = (page - 1) * page_size

            spec = QuerySpec(
                filters=query_filters,
                limit=page_size,
                offset=offset,
                order_by=order_by,
            )
            rows = await backend.list(model_class, spec)

            sensitive_fields = model_admin.get_sensitive_fields()
            list_display = model_admin.get_list_display(request)
            list_display = [f for f in list_display if f not in sensitive_fields]
            items = []
            for row in rows:
                item: dict[str, object] = {"id": row.get("id")}
                for field_name in list_display:
                    value = row.get(field_name)
                    if hasattr(value, "isoformat"):
                        value = value.isoformat()
                    elif value is not None and not isinstance(value, (str, int, float, bool)):
                        value = str(value)
                    item[field_name] = value
                items.append(item)

            total = len(rows)
            if backend.capabilities.supports_count:
                count_spec = QuerySpec(filters=query_filters)
                total = await backend.count(model_class, count_spec)

            return JSONResponse(
                {
                    "items": items,
                    "total": total,
                    "page": page,
                    "per_page": page_size,
                    "total_pages": (total + page_size - 1) // page_size if page_size else 1,
                    "list_display": list_display,
                    "virtual": True,
                }
            )

        qs = model_class.objects.all()

        select_related_fields = model_admin.get_list_select_related(request)
        if select_related_fields:
            qs = qs.select_related(*select_related_fields)

        search_query = request.query_params.get("search", request.query_params.get("q", "")).strip()
        if search_query:
            search_fields = model_admin.get_search_fields(request)
            if search_fields:
                for field in search_fields:
                    if hasattr(qs, "filter"):
                        qs = qs.filter(**{f"{field}__contains": search_query})
                        break

        model_fields = getattr(model_class, "_fields", {})
        allowed_fields = set(model_fields.keys())
        _int_field_types = frozenset(
            {
                "IntegerField",
                "BigIntegerField",
                "PositiveIntegerField",
                "FloatField",
                "DecimalField",
            }
        )
        filters = {}
        for key, value in request.query_params.items():
            if key.startswith("filter_"):
                field_name = key[7:]
                if field_name not in allowed_fields:
                    continue
                field_type = model_fields[field_name].__class__.__name__
                if field_type in ("ForeignKey", "OneToOneField"):
                    fk_col = model_fields[field_name].column_name  # e.g. "category_id"
                    if value.isdigit():
                        filters[fk_col] = value
                    else:
                        filters[f"{fk_col}__icontains"] = value
                elif field_type == "BooleanField":
                    filters[field_name] = value.lower() in ("true", "1", "yes")
                elif field_type in _int_field_types or field_type in ("DateField", "DateTimeField"):
                    filters[field_name] = value
                else:
                    filters[f"{field_name}__icontains"] = value

        if filters:
            qs = qs.filter(**filters)

        sort_field = request.query_params.get("ordering", request.query_params.get("sort", ""))
        if sort_field:
            bare_field = sort_field.lstrip("-")
            if bare_field in allowed_fields:
                qs = qs.order_by(sort_field)
        else:
            ordering = model_admin.get_ordering(request)
            if ordering:
                qs = qs.order_by(*ordering)

        total = await qs.count()

        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except ValueError, TypeError:
            page = 1
        try:
            page_size = min(
                1000,
                max(
                    1,
                    int(
                        request.query_params.get(
                            "per_page",
                            request.query_params.get("page_size", model_admin.list_per_page),
                        )
                    ),
                ),
            )
        except ValueError, TypeError:
            page_size = model_admin.list_per_page
        offset = (page - 1) * page_size

        qs = qs.offset(offset).limit(page_size)
        instances = await qs.all()

        sensitive_fields = model_admin.get_sensitive_fields()

        list_display = model_admin.get_list_display(request)
        list_display = [f for f in list_display if f not in sensitive_fields]
        items = []
        for instance in instances:
            item = {"id": getattr(instance, "id", None)}
            for field_name in list_display:
                value = getattr(instance, field_name, None)
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
                elif value is not None and not isinstance(value, (str, int, float, bool)):
                    value = str(value)
                item[field_name] = value
            items.append(item)

        return JSONResponse(
            {
                "items": items,
                "total": total,
                "page": page,
                "per_page": page_size,
                "total_pages": (total + page_size - 1) // page_size if page_size else 1,
                "list_display": list_display,
            }
        )

    @router.post("/models/{app_label}/{model_name}/")
    async def create_instance_by_app(
        request: Request, app_label: str, model_name: str
    ) -> JSONResponse:
        """Create a new model instance."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_app_and_name(app_label, model_name)
            model_class = admin.get_model_by_app_and_name(app_label, model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{app_label}/{model_name}' not found.") from exc

        if not model_admin.has_add_permission(request):
            raise PermissionDenied(f"No permission to add {model_name}.")

        if "multipart/form-data" in request.headers.get("content-type", ""):
            form = await request.form()
            data = {}
            for k, v in form.items():
                if isinstance(v, str) and (v.startswith("[") or v.startswith("{")):
                    try:
                        data[k] = json.loads(v)
                    except json.JSONDecodeError:
                        data[k] = v
                else:
                    data[k] = v
        else:
            data = await request.json()

        fields = getattr(model_class, "_fields", {})
        coerced_data = {}
        readonly_fields = model_admin.get_readonly_fields(request)
        excluded_fields = set(model_admin.get_exclude(request, None))
        sensitive_fields = set(model_admin.get_sensitive_fields(request))
        field_errors = {}
        child_table_names: set[str] = set()
        child_tables_info = None
        with contextlib.suppress(Exception):
            child_tables_info = model_admin.get_child_tables_info()
        if isinstance(child_tables_info, list):
            for child_model in child_tables_info:
                if isinstance(child_model, dict):
                    name = child_model.get("name")
                    if isinstance(name, str) and name:
                        child_table_names.add(name)

        for field_name, value in data.items():
            if field_name in readonly_fields:
                continue
            if field_name in child_table_names:
                continue
            if value == "__callable__":
                continue
            if field_name not in fields:
                continue
            if field_name in excluded_fields or field_name in sensitive_fields:
                continue
            field = fields[field_name]
            if getattr(field, "primary_key", False) and getattr(field, "auto", False):
                continue
            if isinstance(field, ManyToManyField):
                continue
            try:
                coerced_data[field_name] = coerce_field_value(field, value)
            except ValueError as exc:
                logger.warning(
                    "Field coercion failed for %s.%s.%s: %s", app_label, model_name, field_name, exc
                )
                field_errors[field_name] = str(exc)

        if field_errors:
            logger.warning(
                "Create validation failed for %s.%s: %s",
                app_label,
                model_name,
                field_errors,
            )
            return JSONResponse({"errors": field_errors}, status_code=422)

        try:
            instance = model_class(**coerced_data)
            await instance.save()

            for inline_class in model_admin.child_tables or model_admin.inlines:
                inline = inline_class(model_class)
                child_model = inline.model
                fk_name = inline.fk_name

                if not fk_name:
                    child_fields = getattr(child_model, "_fields", {})
                    for name, f in child_fields.items():
                        if (
                            f.__class__.__name__ in ("ForeignKey", "OneToOneField")
                            and f.resolve_target() == model_class
                        ):
                            fk_name = name
                            break

                if not fk_name:
                    continue

                related_name = child_model.__name__.lower() + "_set"
                raw_rows = data.get(related_name, [])
                if raw_rows is None:
                    incoming_rows = []
                elif isinstance(raw_rows, list):
                    incoming_rows = raw_rows
                else:
                    return JSONResponse(
                        {"errors": {related_name: "Expected a list of row objects."}},
                        status_code=422,
                    )
                child_fields = getattr(child_model, "_fields", {})

                for row in incoming_rows:
                    if not isinstance(row, dict):
                        return JSONResponse(
                            {"errors": {related_name: "Each child row must be an object."}},
                            status_code=422,
                        )
                    if not row.get("id") and not row_has_meaningful_child_data(row, fk_name):
                        continue

                    child_inst = child_model()
                    for f_name, f_val in row.items():
                        if f_name == "id" or f_val is None:
                            continue
                        if f_name not in child_fields:
                            continue
                        f_val = coerce_field_value(child_fields[f_name], f_val)
                        setattr(child_inst, f_name, f_val)
                    parent_pk = instance.id
                    setattr(
                        child_inst,
                        fk_name,
                        str(parent_pk) if isinstance(parent_pk, uuid.UUID) else parent_pk,
                    )
                    if hasattr(inline, "extra_filters") and inline.extra_filters:
                        for f_name, f_val in inline.extra_filters.items():
                            setattr(child_inst, f_name, f_val)
                    await child_inst.save()
        except ValueError as exc:
            logger.warning(
                "Create failed validation for %s.%s: %s",
                app_label,
                model_name,
                str(exc),
            )
            return JSONResponse({"errors": {"__all__": str(exc)}}, status_code=422)
        except sqlalchemy.exc.IntegrityError as exc:
            msg = str(exc.orig) if hasattr(exc, "orig") and exc.orig else str(exc)
            logger.warning(
                "Create failed integrity check for %s.%s: %s",
                app_label,
                model_name,
                msg,
            )
            existing_id = await find_existing_on_unique_violation(model_class, exc, coerced_data)
            if existing_id is not None:
                return JSONResponse(
                    {
                        "errors": {"__all__": "A record with that data already exists."},
                        "existing_id": existing_id,
                        "app_label": app_label,
                        "model_name": model_name,
                    },
                    status_code=409,
                )
            user_msg = (
                msg
                if getattr(settings, "DEBUG", False)
                else "A record with conflicting data already exists."
            )
            return JSONResponse({"errors": {"__all__": user_msg}}, status_code=422)

        asyncio.create_task(
            log_change(
                model_name=model_name,
                object_id=instance.id,
                action=ChangeAction.ADD,
                user=request.user,
                object_repr=str(instance),
            )
        )

        response_data = await serialize_instance_with_children(
            request, model_admin, model_class, instance
        )
        return JSONResponse(response_data, status_code=201)

    @router.get("/models/{app_label}/{model_name}/filters/")
    async def get_filter_options_by_app(
        request: Request, app_label: str, model_name: str
    ) -> JSONResponse:
        """Get available filter options for a model (app-label variant)."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_app_and_name(app_label, model_name)
            model_class = admin.get_model_by_app_and_name(app_label, model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{app_label}/{model_name}' not found.") from exc

        list_filter = model_admin.get_list_filter(request)
        fields = getattr(model_class, "_fields", {})

        filters = []
        for field_name in list_filter:
            if field_name not in fields:
                continue
            field = fields[field_name]
            field_type = field.__class__.__name__
            filter_info: dict = {
                "name": field_name,
                "type": field_type,
                "component": get_field_component_type(field),
                "choices": get_filter_choices(field),
            }

            if not filter_info["choices"]:
                if field_type == "BooleanField":
                    filter_info["choices"] = [
                        {"value": "true", "label": "Yes"},
                        {"value": "false", "label": "No"},
                    ]
                elif field_type in ("ForeignKey", "OneToOneField"):
                    related_model = field.resolve_target()
                    if related_model is not None:
                        try:
                            related_qs = await asyncio.to_thread(
                                lambda rm=related_model: list(rm.objects.all()[:200])
                            )
                            filter_info["choices"] = [
                                {"value": str(obj.id), "label": str(obj)} for obj in related_qs
                            ]
                        except Exception:
                            logger.debug(
                                "Failed to load related model choices for %s",
                                field_name,
                                exc_info=True,
                            )

            filters.append(filter_info)

        return JSONResponse({"filters": filters})

    @router.get("/models/{app_label}/{model_name}/{obj_id}/")
    async def get_instance_by_app(
        request: Request, app_label: str, model_name: str, obj_id: str
    ) -> JSONResponse:
        """Get a single model instance with model info."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_app_and_name(app_label, model_name)
            model_class = admin.get_model_by_app_and_name(app_label, model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{app_label}/{model_name}' not found.") from exc

        obj_id_casted = cast_to_pk_type(model_class, obj_id)
        instance = await model_class.objects.get_or_none(id=obj_id_casted)
        if not instance:
            raise NotFound(f"{model_name} with id {obj_id} not found.")

        if not model_admin.has_view_permission(request, instance):
            raise PermissionDenied(f"No permission to view this {model_name}.")

        response_data = await serialize_instance_with_children(
            request, model_admin, model_class, instance
        )

        model_info = model_admin.get_model_info(request)

        return JSONResponse(
            {
                "instance": response_data,
                "model_info": model_info,
                "readonly_fields": model_admin.get_readonly_fields(request, instance),
                "fieldsets": model_admin.get_fieldsets(request, instance),
            }
        )

    @router.put("/models/{app_label}/{model_name}/{obj_id}/")
    async def update_instance_by_app(
        request: Request, app_label: str, model_name: str, obj_id: str
    ) -> JSONResponse:
        """Update a model instance (PUT/full update)."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_app_and_name(app_label, model_name)
            model_class = admin.get_model_by_app_and_name(app_label, model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{app_label}/{model_name}' not found.") from exc

        obj_id_casted = cast_to_pk_type(model_class, obj_id)
        instance = await model_class.objects.get_or_none(id=obj_id_casted)
        if not instance:
            raise NotFound(f"{model_name} with id {obj_id} not found.")

        if "multipart/form-data" in request.headers.get("content-type", ""):
            form = await request.form()
            data = {}
            for k, v in form.items():
                if isinstance(v, str) and (v.startswith("[") or v.startswith("{")):
                    try:
                        data[k] = json.loads(v)
                    except json.JSONDecodeError:
                        data[k] = v
                else:
                    data[k] = v
        else:
            data = await request.json()

        fields = getattr(model_class, "_fields", {})
        old_data = {}
        for field_name, field_obj in fields.items():
            if isinstance(field_obj, ManyToManyField):
                continue
            old_data[field_name] = getattr(instance, field_name, None)

        readonly_fields = model_admin.get_readonly_fields(request, instance)
        excluded_fields = set(model_admin.get_exclude(request, instance))
        sensitive_fields = set(model_admin.get_sensitive_fields(request, instance))
        new_data = {}
        field_errors = {}
        child_table_names: set[str] = set()
        child_tables_info = None
        with contextlib.suppress(Exception):
            child_tables_info = model_admin.get_child_tables_info()
        if isinstance(child_tables_info, list):
            for child_model in child_tables_info:
                if isinstance(child_model, dict):
                    name = child_model.get("name")
                    if isinstance(name, str) and name:
                        child_table_names.add(name)

        for field_name, value in data.items():
            if field_name in readonly_fields:
                continue
            if field_name in child_table_names:
                continue
            if value == "__callable__":
                continue
            if field_name not in fields:
                continue
            if field_name in excluded_fields or field_name in sensitive_fields:
                continue
            if isinstance(fields[field_name], ManyToManyField):
                continue
            try:
                coerced_value = coerce_field_value(fields[field_name], value)
                setattr(instance, field_name, coerced_value)
                new_data[field_name] = coerced_value
            except ValueError as exc:
                logger.warning(
                    "Field coercion failed for %s.%s.%s: %s", app_label, model_name, field_name, exc
                )
                field_errors[field_name] = str(exc)

        if field_errors:
            logger.warning(
                "Update validation failed for %s.%s (pk=%s): %s",
                app_label,
                model_name,
                obj_id,
                field_errors,
            )
            return JSONResponse({"errors": field_errors}, status_code=422)

        try:
            await instance.save()

            preloaded_children: dict[str, list[dict[str, t.Any]]] = {}

            for inline_class in model_admin.child_tables or model_admin.inlines:
                inline = inline_class(model_class)
                child_model = inline.model
                fk_name = inline.fk_name

                if not fk_name:
                    child_fields = getattr(child_model, "_fields", {})
                    for name, f in child_fields.items():
                        if (
                            f.__class__.__name__ in ("ForeignKey", "OneToOneField")
                            and f.resolve_target() == model_class
                        ):
                            fk_name = name
                            break

                if not fk_name:
                    continue

                related_name = child_model.__name__.lower() + "_set"
                if related_name not in data:
                    continue

                raw_rows = data.get(related_name, [])
                if raw_rows is None:
                    incoming_rows = []
                elif isinstance(raw_rows, list):
                    incoming_rows = raw_rows
                else:
                    return JSONResponse(
                        {"errors": {related_name: "Expected a list of row objects."}},
                        status_code=422,
                    )

                filters = {fk_name: instance.id}
                if hasattr(inline, "extra_filters") and inline.extra_filters:
                    filters.update(inline.extra_filters)
                existing_records = await child_model.objects.filter(**filters).all()
                existing_map = {str(r.id): r for r in existing_records}
                seen_ids = set()

                child_fields = getattr(child_model, "_fields", {})
                child_fields_list = inline.fields or list(child_fields.keys())
                surviving_children: list[dict[str, t.Any]] = []

                for row in incoming_rows:
                    if not isinstance(row, dict):
                        return JSONResponse(
                            {"errors": {related_name: "Each child row must be an object."}},
                            status_code=422,
                        )

                    row_id = str(row.get("id")) if row.get("id") else None
                    row_has_data = row_has_meaningful_child_data(row, fk_name)

                    if row_id and row_id in existing_map and not row_has_data:
                        child_inst = existing_map[row_id]
                        seen_ids.add(row_id)
                    elif not row_id and not row_has_data:
                        continue

                    elif row_id and row_id in existing_map:
                        child_inst = existing_map[row_id]
                        for f_name, f_val in row.items():
                            if f_name in ("id", fk_name) or f_val is None:
                                continue
                            if f_name not in child_fields:
                                continue
                            f_val = coerce_field_value(child_fields[f_name], f_val)
                            setattr(child_inst, f_name, f_val)
                        await child_inst.save()
                        seen_ids.add(row_id)
                    else:
                        child_inst = child_model()
                        for f_name, f_val in row.items():
                            if f_name == "id" or f_val is None:
                                continue
                            if f_name not in child_fields:
                                continue
                            f_val = coerce_field_value(child_fields[f_name], f_val)
                            setattr(child_inst, f_name, f_val)
                        parent_pk = instance.id
                        setattr(
                            child_inst,
                            fk_name,
                            str(parent_pk) if isinstance(parent_pk, uuid.UUID) else parent_pk,
                        )
                        if hasattr(inline, "extra_filters") and inline.extra_filters:
                            for f_name, f_val in inline.extra_filters.items():
                                setattr(child_inst, f_name, f_val)
                        await child_inst.save()
                        if hasattr(child_inst, "id"):
                            seen_ids.add(str(child_inst.id))

                    raw_id = child_inst.id
                    child_data: dict[str, t.Any] = {
                        "id": (
                            raw_id
                            if isinstance(raw_id, (str, int, float, bool, type(None)))
                            else str(raw_id)
                        )
                    }
                    for f_name in child_fields_list:
                        val = getattr(child_inst, f_name, None)
                        if hasattr(val, "isoformat"):
                            val = val.isoformat()
                        elif val is not None and not isinstance(
                            val, (str, int, float, bool, list, dict)
                        ):
                            val = str(val)
                        child_data[f_name] = val
                    surviving_children.append(child_data)

                for r_id, r_obj in existing_map.items():
                    if r_id not in seen_ids:
                        await r_obj.delete()

                preloaded_children[related_name] = surviving_children

        except ValueError as exc:
            logger.warning(
                "Update failed validation for %s.%s (pk=%s): %s",
                app_label,
                model_name,
                obj_id,
                str(exc),
            )
            return JSONResponse({"errors": {"__all__": str(exc)}}, status_code=422)
        except sqlalchemy.exc.IntegrityError as exc:
            msg = str(exc.orig) if hasattr(exc, "orig") and exc.orig else str(exc)
            logger.warning(
                "Update failed integrity check for %s.%s (pk=%s): %s",
                app_label,
                model_name,
                obj_id,
                msg,
            )
            user_msg = (
                msg
                if getattr(settings, "DEBUG", False)
                else "A record with conflicting data already exists."
            )
            return JSONResponse({"errors": {"__all__": user_msg}}, status_code=422)

        changes = compute_changes(old_data, new_data)
        if changes:
            asyncio.create_task(
                log_change(
                    model_name=model_name,
                    object_id=instance.id,
                    action=ChangeAction.CHANGE,
                    changes=changes,
                    user=request.user,
                    object_repr=str(instance),
                )
            )

        response_data = await serialize_instance_with_children(
            request,
            model_admin,
            model_class,
            instance,
            preloaded_children=preloaded_children,
        )
        return JSONResponse(response_data)

    @router.delete("/models/{app_label}/{model_name}/{obj_id}/")
    async def delete_instance_by_app(
        request: Request, app_label: str, model_name: str, obj_id: str
    ) -> JSONResponse:
        """Delete a model instance."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_app_and_name(app_label, model_name)
            model_class = admin.get_model_by_app_and_name(app_label, model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{app_label}/{model_name}' not found.") from exc

        obj_id_casted = cast_to_pk_type(model_class, obj_id)
        instance = await model_class.objects.get_or_none(id=obj_id_casted)
        if not instance:
            raise NotFound(f"{model_name} with id {obj_id} not found.")

        if not model_admin.has_delete_permission(request, instance):
            raise PermissionDenied(f"No permission to delete this {model_name}.")

        object_repr = str(instance)
        await instance.delete()

        with contextlib.suppress(Exception):
            await log_change(
                model_name=model_name,
                object_id=obj_id,
                action=ChangeAction.DELETE,
                user=request.user,
                object_repr=object_repr,
            )

        return JSONResponse({"detail": f"{model_name} deleted successfully."})

    @router.post("/models/{app_label}/{model_name}/bulk-action/")
    @rate_limit(max_requests=10, window_seconds=60)
    async def bulk_action_by_app(request: Request, app_label: str, model_name: str) -> JSONResponse:
        """Execute a batch action on selected instances."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            admin.get_model_admin_by_app_and_name(app_label, model_name)
            model_class = admin.get_model_by_app_and_name(app_label, model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{app_label}/{model_name}' not found.") from exc

        meta = getattr(model_class, "_meta", None)
        if meta and isinstance(getattr(meta, "single", None), bool) and meta.single:
            raise PermissionDenied("Bulk actions are not supported for single-instance models.")

        data = await request.json()
        action_name = data.get("action")
        ids = data.get("ids", [])

        if not action_name:
            raise ValidationError({"detail": "Action name is required."})

        if not ids:
            raise ValidationError({"detail": "No IDs provided."})

        if len(ids) > 1000:
            raise ValidationError({"detail": "Cannot act on more than 1000 items at once."})

        action = get_action(action_name)
        if not action:
            raise NotFound(f"Action '{action_name}' not found.")

        if not action.has_permission(request):
            raise PermissionDenied(f"No permission to execute action '{action_name}'.")

        model_admin = admin.get_model_admin_by_app_and_name(app_label, model_name)
        qs = model_class.objects.filter(id__in=ids)
        result: ActionResult = await action.execute(qs, request, model_admin=model_admin)

        return JSONResponse(
            {
                "success": result.success,
                "count": result.count,
                "message": result.message,
                "errors": result.errors,
            }
        )

    @router.get("/models/{app_label}/{model_name}/export/")
    @rate_limit(max_requests=5, window_seconds=60)
    async def export_instances_by_app(
        request: Request, app_label: str, model_name: str
    ) -> Response:
        """Export instances to CSV or JSON."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_app_and_name(app_label, model_name)
            model_class = admin.get_model_by_app_and_name(app_label, model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{app_label}/{model_name}' not found.") from exc

        if not check_model_permission(request, model_class, "view"):
            raise PermissionDenied(f"No permission to export {model_name}.")

        ids_param = request.query_params.get("ids", "")
        ids = [int(i) for i in ids_param.split(",") if i.strip().isdigit()] if ids_param else []

        max_export = getattr(settings, "ADMIN_MAX_EXPORT_ROWS", 10000)
        if ids:
            qs = model_class.objects.filter(id__in=ids[:max_export])
        else:
            qs = model_class.objects.all().limit(max_export)

        instances = await qs.all()

        output = io.StringIO()
        list_display = model_admin.get_list_display(request)
        fieldnames = ["id"] + [f for f in list_display if f != "id"]

        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for instance in instances:
            row = {"id": instance.id}
            for field_name in list_display:
                value = getattr(instance, field_name, "")
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
                row[field_name] = sanitize_csv_cell(value)
            writer.writerow(row)

        csv_content = output.getvalue()
        output.close()

        safe_name = sanitize_filename(model_name)
        return Response(
            content=csv_content,
            status_code=200,
            headers={
                "Content-Type": "text/csv",
                "Content-Disposition": f'attachment; filename="{safe_name}.csv"',
            },
        )

    @router.get("/models/{app_label}/{model_name}/{obj_id}/history/")
    async def get_instance_history_by_app(
        request: Request, app_label: str, model_name: str, obj_id: str
    ) -> JSONResponse:
        """Get change history for a model instance."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_class = admin.get_model_by_app_and_name(app_label, model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{app_label}/{model_name}' not found.") from exc

        obj_id_casted = cast_to_pk_type(model_class, obj_id)
        instance = await model_class.objects.get_or_none(id=obj_id_casted)
        if not instance:
            raise NotFound(f"{model_name} with id {obj_id} not found.")

        history_records = await get_change_history(model_name, obj_id)

        history = []
        for record in history_records:
            history.append(
                {
                    "id": record.id,
                    "action": record.action,
                    "changed_fields": record.get_changed_fields_dict(),
                    "changed_by": record.changed_by_username,
                    "change_time": (record.change_time.isoformat() if record.change_time else None),
                    "message": record.change_message,
                }
            )

        return JSONResponse({"history": history})

    @router.get("/models/{model_name}/")
    async def list_instances(request: Request, model_name: str) -> JSONResponse:
        """List instances of a model with pagination, search, and filtering."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_name(model_name)
            model_class = admin.get_model_by_name(model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{model_name}' not found.") from exc

        if not check_model_permission(request, model_class, "view"):
            try:
                page = max(1, int(request.query_params.get("page", 1)))
            except ValueError, TypeError:
                page = 1
            try:
                per_page = max(
                    1,
                    int(
                        request.query_params.get(
                            "per_page",
                            request.query_params.get("page_size", model_admin.list_per_page),
                        )
                    ),
                )
            except ValueError, TypeError:
                per_page = model_admin.list_per_page
            return JSONResponse(
                {
                    "items": [],
                    "total": 0,
                    "page": page,
                    "per_page": per_page,
                    "total_pages": 0,
                    "list_display": model_admin.get_list_display(request),
                    "permission_denied": True,
                    "permission_message": f"You do not have permission to view {model_name}.",
                }
            )

        qs = model_class.objects.all()

        search_query = request.query_params.get("q", "").strip()
        if search_query:
            search_fields = model_admin.get_search_fields(request)
            if search_fields:
                for field in search_fields:
                    if hasattr(qs, "filter"):
                        qs = qs.filter(**{f"{field}__contains": search_query})
                        break

        allowed_fields = set(getattr(model_class, "_fields", {}).keys())
        filters = {}
        for key, value in request.query_params.items():
            if key.startswith("filter_"):
                field_name = key[7:]  # Remove "filter_" prefix
                if field_name in allowed_fields:
                    filters[field_name] = value

        if filters:
            qs = qs.filter(**filters)

        sort_field = request.query_params.get("sort", "")
        if sort_field:
            bare_field = sort_field.lstrip("-")
            if bare_field in allowed_fields:
                qs = qs.order_by(sort_field)
        else:
            ordering = model_admin.get_ordering(request)
            if ordering:
                qs = qs.order_by(*ordering)

        total = await qs.count()

        try:
            page = max(1, int(request.query_params.get("page", 1)))
        except ValueError, TypeError:
            page = 1
        try:
            page_size = min(
                1000,
                max(1, int(request.query_params.get("page_size", model_admin.list_per_page))),
            )
        except ValueError, TypeError:
            page_size = model_admin.list_per_page
        offset = (page - 1) * page_size

        qs = qs.offset(offset).limit(page_size)
        instances = await qs.all()

        list_display = model_admin.get_list_display(request)
        items = []
        for instance in instances:
            item = {"id": getattr(instance, "id", None)}
            for field_name in list_display:
                value = getattr(instance, field_name, None)
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
                elif value is not None and not isinstance(value, (str, int, float, bool)):
                    value = str(value)
                item[field_name] = value
            items.append(item)

        return JSONResponse(
            {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
                "list_display": list_display,
            }
        )

    @router.post("/models/{model_name}/")
    async def create_instance(request: Request, model_name: str) -> JSONResponse:
        """Create a new model instance."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_name(model_name)
            model_class = admin.get_model_by_name(model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{model_name}' not found.") from exc

        if not model_admin.has_add_permission(request):
            raise PermissionDenied(f"No permission to add {model_name}.")

        data = await request.json()

        fields = getattr(model_class, "_fields", {})
        coerced_data = {}
        readonly_fields = model_admin.get_readonly_fields(request)
        field_errors = {}

        for field_name, value in data.items():
            if field_name in readonly_fields:
                continue
            try:
                if field_name in fields:
                    logger.debug("Coercing field %s via coerce_field_value", field_name)
                    coerced_data[field_name] = coerce_field_value(fields[field_name], value)
                else:
                    continue
            except ValueError as exc:
                logger.error("Coercion exception for %s: %s", field_name, exc)
                field_errors[field_name] = str(exc)

        if field_errors:
            return JSONResponse({"errors": field_errors}, status_code=422)

        instance = model_class(**coerced_data)
        await instance.save()

        with contextlib.suppress(Exception):
            await log_change(
                model_name=model_name,
                object_id=instance.id,
                action=ChangeAction.ADD,
                user=request.user,
                object_repr=str(instance),
            )

        response_data = {"id": instance.id}
        for field_name, field_obj in fields.items():
            if isinstance(field_obj, ManyToManyField):
                continue
            value = getattr(instance, field_name, None)
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            response_data[field_name] = value

        return JSONResponse(response_data, status_code=201)

    @router.get("/models/{model_name}/{obj_id}/")
    async def get_instance(request: Request, model_name: str, obj_id: str) -> JSONResponse:
        """Get a single model instance."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_name(model_name)
            model_class = admin.get_model_by_name(model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{model_name}' not found.") from exc

        obj_id_casted = cast_to_pk_type(model_class, obj_id)
        instance = await model_class.objects.get_or_none(id=obj_id_casted)
        if not instance:
            raise NotFound(f"{model_name} with id {obj_id} not found.")

        if not model_admin.has_view_permission(request, instance):
            raise PermissionDenied(f"No permission to view this {model_name}.")

        fields = getattr(model_class, "_fields", {})
        response_data = {"id": instance.id}
        for field_name, field_obj in fields.items():
            if isinstance(field_obj, ManyToManyField):
                continue
            value = getattr(instance, field_name, None)
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            elif value is not None and not isinstance(value, (str, int, float, bool, list, dict)):
                value = str(value)
            response_data[field_name] = value

        model_info = model_admin.get_model_info(request)

        return JSONResponse(
            {
                "instance": response_data,
                "model_info": model_info,
                "readonly_fields": model_admin.get_readonly_fields(request, instance),
                "fieldsets": model_admin.get_fieldsets(request, instance),
            }
        )

    @router.patch("/models/{model_name}/{obj_id}/")
    async def update_instance(request: Request, model_name: str, obj_id: str) -> JSONResponse:
        """Update a model instance."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_name(model_name)
            model_class = admin.get_model_by_name(model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{model_name}' not found.") from exc

        obj_id_casted = cast_to_pk_type(model_class, obj_id)
        instance = await model_class.objects.get_or_none(id=obj_id_casted)
        if not instance:
            raise NotFound(f"{model_name} with id {obj_id} not found.")

        if not model_admin.has_change_permission(request, instance):
            raise PermissionDenied(f"No permission to change this {model_name}.")

        data = await request.json()

        fields = getattr(model_class, "_fields", {})
        old_data = {}
        for field_name, field_obj in fields.items():
            if isinstance(field_obj, ManyToManyField):
                continue
            old_data[field_name] = getattr(instance, field_name, None)

        readonly_fields = model_admin.get_readonly_fields(request, instance)
        new_data = {}
        field_errors = {}

        for field_name, value in data.items():
            if field_name in readonly_fields:
                continue
            try:
                if field_name in fields:
                    coerced_value = coerce_field_value(fields[field_name], value)
                    setattr(instance, field_name, coerced_value)
                    new_data[field_name] = coerced_value
                else:
                    continue
            except ValueError as exc:
                field_errors[field_name] = str(exc)

        if field_errors:
            return JSONResponse({"errors": field_errors}, status_code=422)

        await instance.save()

        changes = compute_changes(old_data, new_data)
        if changes:
            asyncio.create_task(
                log_change(
                    model_name=model_name,
                    object_id=instance.id,
                    action=ChangeAction.CHANGE,
                    changes=changes,
                    user=request.user,
                    object_repr=str(instance),
                )
            )

        response_data = {"id": instance.id}
        for field_name, field_obj in fields.items():
            if isinstance(field_obj, ManyToManyField):
                continue
            value = getattr(instance, field_name, None)
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            response_data[field_name] = value

        return JSONResponse(response_data)

    @router.delete("/models/{model_name}/{obj_id}/")
    async def delete_instance(request: Request, model_name: str, obj_id: str) -> JSONResponse:
        """Delete a model instance."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_name(model_name)
            model_class = admin.get_model_by_name(model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{model_name}' not found.") from exc

        obj_id_casted = cast_to_pk_type(model_class, obj_id)
        instance = await model_class.objects.get_or_none(id=obj_id_casted)
        if not instance:
            raise NotFound(f"{model_name} with id {obj_id} not found.")

        if not model_admin.has_delete_permission(request, instance):
            raise PermissionDenied(f"No permission to delete this {model_name}.")

        object_repr = str(instance)
        await instance.delete()

        with contextlib.suppress(Exception):
            await log_change(
                model_name=model_name,
                object_id=obj_id,
                action=ChangeAction.DELETE,
                user=request.user,
                object_repr=object_repr,
            )

        return JSONResponse({"detail": f"{model_name} deleted successfully."})

    @router.post("/models/{model_name}/bulk-delete/")
    @rate_limit(max_requests=10, window_seconds=60)
    async def bulk_delete(request: Request, model_name: str) -> JSONResponse:
        """Delete multiple instances."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_name(model_name)
            model_class = admin.get_model_by_name(model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{model_name}' not found.") from exc

        data = await request.json()
        ids = data.get("ids", [])

        if not ids:
            raise ValidationError({"detail": "No IDs provided."})

        if len(ids) > 1000:
            raise ValidationError({"detail": "Cannot delete more than 1000 items at once."})

        if not model_admin.has_delete_permission(request):
            raise PermissionDenied(f"No permission to delete {model_name}.")

        ids_casted = [cast_to_pk_type(model_class, i) for i in ids]
        count = await model_class.objects.filter(id__in=ids_casted).delete()

        with contextlib.suppress(Exception):
            for obj_id in ids:
                await log_change(
                    model_name=model_name,
                    object_id=obj_id,
                    action=ChangeAction.DELETE,
                    user=request.user,
                    object_repr=f"{model_name} #{obj_id}",
                )

        return JSONResponse(
            {
                "detail": f"Deleted {count} item(s).",
                "count": count,
            }
        )

    @router.post("/models/{model_name}/bulk-action/")
    @rate_limit(max_requests=10, window_seconds=60)
    async def bulk_action(request: Request, model_name: str) -> JSONResponse:
        """Execute a batch action on selected instances."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            admin.get_model_admin_by_name(model_name)
            model_class = admin.get_model_by_name(model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{model_name}' not found.") from exc

        data = await request.json()
        action_name = data.get("action")
        ids = data.get("ids", [])

        if not action_name:
            raise ValidationError({"detail": "Action name is required."})

        if not ids:
            raise ValidationError({"detail": "No IDs provided."})

        if len(ids) > 1000:
            raise ValidationError({"detail": "Cannot act on more than 1000 items at once."})

        action = get_action(action_name)
        if not action:
            raise NotFound(f"Action '{action_name}' not found.")

        if not action.has_permission(request):
            raise PermissionDenied(f"No permission to execute action '{action_name}'.")

        qs = model_class.objects.filter(id__in=ids)

        model_admin = admin.get_model_admin_by_name(model_name)
        result: ActionResult = await action.execute(qs, request, model_admin=model_admin)

        return JSONResponse(
            {
                "success": result.success,
                "count": result.count,
                "message": result.message,
                "errors": result.errors,
            }
        )

    @router.get("/models/{model_name}/search/")
    async def search_instances(request: Request, model_name: str) -> JSONResponse:
        """Search instances of a model."""
        return await list_instances(request, model_name)

    @router.get("/models/{model_name}/filters/")
    async def get_filter_options(request: Request, model_name: str) -> JSONResponse:
        """Get available filter options for a model."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_name(model_name)
            model_class = admin.get_model_by_name(model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{model_name}' not found.") from exc

        list_filter = model_admin.get_list_filter(request)
        fields = getattr(model_class, "_fields", {})

        filters = []
        for field_name in list_filter:
            if field_name in fields:
                field = fields[field_name]
                filter_info = {
                    "name": field_name,
                    "type": field.__class__.__name__,
                    "component": get_field_component_type(field),
                    "choices": get_filter_choices(field),
                }

                if not filter_info["choices"] and field.__class__.__name__ == "BooleanField":
                    filter_info["choices"] = [
                        {"value": True, "label": "Yes"},
                        {"value": False, "label": "No"},
                    ]

                filters.append(filter_info)

        return JSONResponse({"filters": filters})

    @router.post("/models/{model_name}/export/")
    @rate_limit(max_requests=5, window_seconds=60)
    async def export_instances(request: Request, model_name: str) -> Response:
        """Export instances to CSV."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_admin = admin.get_model_admin_by_name(model_name)
            model_class = admin.get_model_by_name(model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{model_name}' not found.") from exc

        if not check_model_permission(request, model_class, "view"):
            raise PermissionDenied(f"No permission to export {model_name}.")

        data = await request.json()
        ids = data.get("ids", [])

        max_export = getattr(settings, "ADMIN_MAX_EXPORT_ROWS", 10000)
        if ids:
            qs = model_class.objects.filter(id__in=ids[:max_export])
        else:
            qs = model_class.objects.all().limit(max_export)

        instances = await qs.all()

        output = io.StringIO()
        list_display = model_admin.get_list_display(request)
        fieldnames = ["id"] + [f for f in list_display if f != "id"]

        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for instance in instances:
            row = {"id": instance.id}
            for field_name in list_display:
                value = getattr(instance, field_name, "")
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
                row[field_name] = sanitize_csv_cell(value)
            writer.writerow(row)

        csv_content = output.getvalue()
        output.close()

        safe_name = sanitize_filename(model_name)
        return Response(
            content=csv_content,
            status_code=200,
            headers={
                "Content-Type": "text/csv",
                "Content-Disposition": f'attachment; filename="{safe_name}.csv"',
            },
        )

    @router.get("/models/{model_name}/{obj_id}/history/")
    async def get_instance_history(request: Request, model_name: str, obj_id: str) -> JSONResponse:
        """Get change history for a model instance."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        try:
            model_class = admin.get_model_by_name(model_name)
        except NotRegistered as exc:
            raise NotFound(f"Model '{model_name}' not found.") from exc

        obj_id_casted = cast_to_pk_type(model_class, obj_id)
        instance = await model_class.objects.get_or_none(id=obj_id_casted)
        if not instance:
            raise NotFound(f"{model_name} with id {obj_id} not found.")

        history_records = await get_change_history(model_name, obj_id)

        history = []
        for record in history_records:
            history.append(
                {
                    "id": record.id,
                    "action": record.action,
                    "changed_fields": record.get_changed_fields_dict(),
                    "changed_by": record.changed_by_username,
                    "change_time": (record.change_time.isoformat() if record.change_time else None),
                    "message": record.change_message,
                }
            )

        return JSONResponse({"history": history})

    @router.get("/models/{app_label}/{model_name}/fk-search/")
    async def fk_search(request: Request, app_label: str, model_name: str) -> JSONResponse:
        """Search related model for ForeignKey field autocomplete.

        Query params:
            q: Search query
            limit: Max results (default 20)

        Returns:
            List of items with id and label (__str__ representation).
        """
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        model_class = None

        with contextlib.suppress(NotRegistered):
            model_class = admin.get_model_by_app_and_name(app_label, model_name)

        if model_class is None:
            raise NotFound(f"Model '{app_label}/{model_name}' not found.")

        query = request.query_params.get("q", "").strip()
        try:
            limit = min(max(int(request.query_params.get("limit", 20)), 1), 100)
        except ValueError, TypeError:
            limit = 20

        qs = model_class.objects.all()

        if query:
            fields = getattr(model_class, "_fields", {})
            search_fields = []
            for field_name, field in fields.items():
                field_type = field.__class__.__name__
                if field_type in ("CharField", "TextField", "EmailField"):
                    search_fields.append(field_name)

            if search_fields:
                qs = qs.filter(**{f"{search_fields[0]}__contains": query})

        qs = qs.limit(limit)
        instances = await qs.all()

        items = []
        for instance in instances:
            items.append(
                {
                    "value": instance.id,
                    "label": str(instance),
                }
            )

        return JSONResponse({"items": items})

    @router.get("/plugins/")
    async def list_plugins(request: Request) -> JSONResponse:
        """List available admin plugins."""
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        return JSONResponse({"plugins": []})

    @router.get("/search/")
    @rate_limit(max_requests=30, window_seconds=60)
    async def global_search(request: Request) -> JSONResponse:
        """Search across all registered models.

        Query params:
            q: Search query string
            limit: Max results per model (default 5)
        """
        if not check_admin_access(request):
            raise PermissionDenied("Admin access required.")

        query = request.query_params.get("q", "").strip()
        if not query:
            return JSONResponse({"results": []})

        limit_per_model = 5
        max_total = 50

        async def _search_model(
            model_class: type, model_admin: ModelAdmin, search_fields: list[str]
        ) -> list[dict[str, t.Any]]:
            qs = model_class.objects.all()
            qs = qs.filter(**{f"{search_fields[0]}__contains": query})
            instances = await qs.limit(limit_per_model).all()
            return [
                {
                    "id": inst.id,
                    "display": str(inst),
                    "model_name": model_class.__name__.lower(),
                    "app_label": admin._get_app_label(model_class),
                }
                for inst in instances
            ]

        tasks = []
        for model_class, model_admin in admin.get_all_models():
            if not check_model_permission(request, model_class, "view"):
                continue

            search_fields = model_admin.get_search_fields(request)
            if not search_fields:
                fields = getattr(model_class, "_fields", {})
                for field_name in ["name", "title", "subject", "username", "email"]:
                    if field_name in fields:
                        search_fields = [field_name]
                        break

            if not search_fields:
                continue

            tasks.append(_search_model(model_class, model_admin, search_fields))

        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        results: list[dict[str, t.Any]] = []
        for task_result in all_results:
            if isinstance(task_result, Exception):
                continue
            results.extend(task_result)
            if len(results) >= max_total:
                results = results[:max_total]
                break

        return JSONResponse({"results": results})

    return router
